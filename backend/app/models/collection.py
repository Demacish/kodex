from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Column, DateTime, Enum, ForeignKey, Integer, String, Table, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import CollectionType

if TYPE_CHECKING:
    from app.models.book import Book


# Association table for manual collections (smart collections have no rows
# here — their contents are computed from `rule` at query time).
collection_books = Table(
    "collection_books",
    Base.metadata,
    Column("collection_id", ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True),
    Column("book_id", ForeignKey("books.id", ondelete="CASCADE"), primary_key=True),
    # Manual reading-order position within the collection, set via
    # PUT /collections/{id}/order (see collections.py). NULL until an
    # admin explicitly reorders a collection at least once — a book added
    # afterwards via add_books_to_collection also starts out NULL, and
    # sorts after every already-positioned book (see _resolve_book_ids'
    # sort key) rather than needing a position assigned immediately.
    Column("position", Integer, nullable=True),
)


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    collection_type: Mapped[CollectionType] = mapped_column(Enum(CollectionType, native_enum=False))

    # Only set for smart collections — a small JSON rule tree evaluated
    # against book metadata at query time, e.g.
    # {"all": [{"field": "genre", "op": "eq", "value": "Fantasy"}]}
    rule: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # A manually uploaded cover, relative to settings.covers_dir (same
    # storage convention as BookMetadata.cover_path) — takes priority over
    # the auto-computed "first book's cover" the Collections page falls
    # back to otherwise (see collections.py's list_collections). NULL
    # means no custom cover has been set.
    cover_image_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    books: Mapped[list[Book]] = relationship(secondary=collection_books)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Collection id={self.id} name={self.name!r} type={self.collection_type}>"
