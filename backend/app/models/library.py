from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import LibraryType

if TYPE_CHECKING:
    from app.models.book import Book
    from app.models.series import Series


class Library(Base):
    """A root folder that gets scanned for books, e.g. "Serier" or "Manga"."""

    __tablename__ = "libraries"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    # Path relative to settings.libraries_root, e.g. "serier". Kept relative
    # so the same database works whether the app runs on the host or in a
    # container with a different mount point.
    path: Mapped[str] = mapped_column(String(1024), unique=True)
    library_type: Mapped[LibraryType] = mapped_column(Enum(LibraryType, native_enum=False))

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_scanned_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_fulltext_indexed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # How books are grouped into series: folder | metadata | comicvine (see
    # kodex.matching.group). Libraries carried over from v1 get "folder",
    # which is what v1 did.
    grouping_strategy: Mapped[str] = mapped_column(String(16), default="metadata", server_default="metadata")
    # Kodex never writes into a read-only library (no write-back, uploads,
    # conversions or sorting moves). Writing metadata back into the files
    # (ComicInfo.xml, series.json) is opt-in per library.
    read_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    write_back: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))

    series: Mapped[list[Series]] = relationship(back_populates="library", cascade="all, delete-orphan")
    books: Mapped[list[Book]] = relationship(back_populates="library", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Library id={self.id} name={self.name!r}>"
