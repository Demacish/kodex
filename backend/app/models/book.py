from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.elements import ColumnElement

from app.database import Base
from app.models.enums import BookEditionType, BookFormat

if TYPE_CHECKING:
    from app.models.library import Library
    from app.models.metadata import BookMetadata
    from app.models.reading_progress import ReadingProgress
    from app.models.series import Series


class Book(Base):
    """A single readable file (or an image-folder treated as one)."""

    __tablename__ = "books"
    __table_args__ = (UniqueConstraint("library_id", "file_path", name="uq_book_library_path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"))
    series_id: Mapped[int | None] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), nullable=True)

    # Path relative to the library root.
    file_path: Mapped[str] = mapped_column(String(2048))
    file_format: Mapped[BookFormat] = mapped_column(Enum(BookFormat, native_enum=False))
    # BigInteger, not Integer: a 32-bit int overflows on anything over
    # ~2.1GB, which real-world compendium/collection archives exceed —
    # found 2026-09-10 when a 2.3GB file crashed the whole scan (see
    # scanner.py's rollback fix for how it also took out every subsequent
    # file in the same run, not just this one).
    file_size: Mapped[int] = mapped_column(BigInteger)
    # Used to skip re-processing unchanged files on rescan.
    file_mtime: Mapped[float] = mapped_column(Float)

    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Issue/volume/chapter number within the series, for sorting. Stored as a
    # float so "12.5" (a one-shot between issues) sorts correctly.
    number: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Single numbered issue vs. a collected edition (TPB/omnibus/deluxe/
    # etc.) — see BookEditionType's own docstring for why this exists.
    # Auto-detected at scan time from the filename (see scanner.py's
    # _upsert_book and comicinfo_writer.py's detect_edition_type) and
    # settable by hand via PATCH /books/{id} — same "re-derived on every
    # scan of a changed file, not a one-time lock" caveat Book.number
    # already has, not a new inconsistency introduced here.
    edition_type: Mapped[BookEditionType] = mapped_column(
        Enum(BookEditionType, native_enum=False),
        default=BookEditionType.ISSUE,
        server_default=BookEditionType.ISSUE.name,
    )

    # Content fingerprint shared across Kodex servers and KOReader devices —
    # KOReader's partial-MD5 document hash for a file, a name+size hash for
    # an image folder (see app/scanning/fingerprint.py). Set by the scanner
    # (also backfilled for unchanged books); null until a scan has seen the
    # book since this column was added.
    content_hash: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # What the book is, unchanged by metadata written into the file: a hash
    # over its pages (see kodex.formats.identity). Duplicates and moved
    # files are found by it.
    content_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # SHA-256 of the whole file, for apps verifying a download, and the
    # "size:mtime" it was taken at (made on first ask, kodex.library.digest).
    file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_sha256_of: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Which source the generated covers were made from (kodex.library.covers).
    cover_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Perceptual hash of the cover (kodex.matching.covers.phash), for finding
    # the same book in two different files.
    cover_phash: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # --- Matching (kodex.matching) ---
    # issue | collected | annual | special | one_shot | chapter | volume | book
    format: Mapped[str] = mapped_column(String(16), default="issue", server_default="issue")
    # The number exactly as written ("1.MU", "13.5"); `number` above is its
    # numeric sort key.
    number_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    volume_number: Mapped[str | None] = mapped_column(String(16), nullable=True)
    chapter_number: Mapped[str | None] = mapped_column(String(16), nullable=True)
    scan_group: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Matched to a series whose run doesn't list this book's number.
    issue_unresolved: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("books.id", ondelete="SET NULL"), nullable=True)
    # Put in its series by hand: grouping never moves it again.
    series_locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # kodex.matching.parse's reading of the file name, shown in the review
    # queue (many "wrong matches" are really parser mistakes).
    parsed: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # [width, height] per page in reading order (None for an unreadable
    # page) — see app/scanning/dimensions.py. Null until computed: during a
    # scan for CBZ/image folders, by a background job for CBR.
    page_dimensions: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Set by the scanner when this book's file is no longer on disk (moved
    # by the sorting feature, renamed or deleted), cleared again as soon as
    # a scan finds it back. Non-null hides the book everywhere a reader
    # browses (see visible_books below) without losing its reading
    # progress, metadata or collection memberships. Admins list and
    # restore hidden books via GET /books/missing and POST
    # /books/{id}/restore.
    missing_since: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set by "Visa igen" (POST /books/{id}/restore): keep showing this book
    # even though its file is gone, instead of re-hiding it on the next
    # scan. Reset once the file turns up again. Null on rows from before
    # this column existed, which means the same as False.
    keep_visible_when_missing: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)

    added_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    library: Mapped[Library] = relationship(back_populates="books")
    series: Mapped[Series | None] = relationship(back_populates="books")
    book_metadata: Mapped[BookMetadata | None] = relationship(
        back_populates="book", cascade="all, delete-orphan", uselist=False
    )
    reading_progress: Mapped[list[ReadingProgress]] = relationship(back_populates="book", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Book id={self.id} file_path={self.file_path!r}>"


def visible_books() -> ColumnElement[bool]:
    """Filter clause for books readers should see: everything except books
    whose file is missing (Book.missing_since). Use in every query that
    lists books, or counts them, for browsing."""
    return Book.missing_since.is_(None)
