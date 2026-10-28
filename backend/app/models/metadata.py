from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import MetadataSource

if TYPE_CHECKING:
    from app.models.book import Book


class BookMetadata(Base):
    """Descriptive metadata for a Book — one row per book.

    `raw` keeps the original embedded metadata (e.g. the full parsed
    ComicInfo.xml) around so a future re-import or a smarter enrichment pass
    doesn't need to re-read the file.
    """

    __tablename__ = "book_metadata"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), unique=True)

    title: Mapped[str] = mapped_column(String(500))
    sort_title: Mapped[str] = mapped_column(String(500))
    authors: Mapped[list[str]] = mapped_column(JSON, default=list)
    genres: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Story arcs / crossover events this issue belongs to (ComicInfo.xml's
    # <StoryArc>, comma-separated — e.g. "Silent Tides", "Absolute Universe")
    # — the same field Kavita/Komga read for arc-based reading lists. Lets a
    # smart collection group books across series, not just within one (see
    # kodex/collections/rules.py) — that's the whole point of an arc: it
    # crosses series boundaries.
    story_arcs: Mapped[list[str]] = mapped_column(JSON, default=list)
    # This issue's position *within* each arc (not its regular series
    # number, which may differ) — {"Silent Tides": 3.0} — from
    # ComicInfo.xml's parallel <StoryArcNumber> list. Keyed by arc name
    # rather than kept as a second parallel list so it survives a
    # mismatched-length StoryArc/StoryArcNumber pair in a malformed file,
    # and so a lookup doesn't depend on list order lining up. Only used to
    # order a smart collection's books when its rule is scoped to one arc
    # (see app/api/routes/collections.py) — reading order across a
    # crossover is the reason this field exists at all.
    story_arc_numbers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    isbn: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Relative path (under settings.covers_dir) to a cached cover image.
    cover_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    source: Mapped[MetadataSource] = mapped_column(
        Enum(MetadataSource, native_enum=False), default=MetadataSource.EMBEDDED
    )
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Which enrichment provider(s) last matched this book, and their ids —
    # e.g. {"comicvine_volume_id": 1234, "comicvine_issue_id": 5678} or
    # {"anilist_id": 42} or {"open_library_key": "/works/OL123W"}. Lets a
    # future re-run skip the search step and go straight to the known
    # record, and avoids re-matching (and potentially mismatching) a book
    # that's already been enriched once.
    external_ids: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Fields set by hand; automation never overwrites them. Replaces the
    # all-or-nothing source == MANUAL lock, which v1 code still sets.
    locked_fields: Mapped[list[str]] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    enriched_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    book: Mapped[Book] = relationship(back_populates="book_metadata")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BookMetadata book_id={self.book_id} title={self.title!r}>"
