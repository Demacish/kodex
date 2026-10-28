from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.book import Book


class ContentIndexEntry(Base):
    """One chapter (EPUB) or page (PDF) of extracted full text.

    Not populated by the default scan — filled in by the manual, per-library
    full-text indexing job (see the architecture plan's "Sök och indexering"
    section). `position` is a chapter path for EPUB or a page number for PDF,
    used to jump straight to the hit in the reader.
    """

    __tablename__ = "content_index_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)

    position: Mapped[str] = mapped_column(String(512))
    text: Mapped[str] = mapped_column(Text)

    book: Mapped[Book] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ContentIndexEntry book_id={self.book_id} position={self.position!r}>"
