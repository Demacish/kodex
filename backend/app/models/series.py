from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.book import Book
    from app.models.library import Library


class Series(Base):
    """A grouping of books under a library, normally one folder per series."""

    __tablename__ = "series"
    __table_args__ = (
        Index("ix_series_library_norm_title", "library_id", "norm_title"),
        Index("uq_series_library_group_key", "library_id", "group_key", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"))

    title: Mapped[str] = mapped_column(String(500))
    sort_title: Mapped[str] = mapped_column(String(500))
    # Path relative to the library root, e.g. "One Piece". Cosmetic/legacy
    # once comicvine_volume_id is set (see below) — no longer used to look
    # a series up, just kept for display and for series that never get a
    # provider match at all.
    path: Mapped[str] = mapped_column(String(1024))

    # Set the first time any book in this series gets matched to a Comic
    # Vine volume (see app/enrichment/engine.py's reparenting logic) — the
    # real grouping key from then on. Without this, scanner.py's
    # _get_or_create_series groups purely by folder name, so every
    # differently-tagged release of the same series ("Absolute Corvid 001
    # (2024) (Webrip) (...)", "... 002 (2025) (...)") becomes its own
    # single-book "series". Nullable: most series won't have this until
    # enrichment actually runs, and it stays null forever for the EBOOKS/
    # MANGA library types with no volume-id provider (AniList uses a
    # different id space entirely — see release_check.py). Only enforced
    # unique per-library at the application level (query-then-create in
    # engine.py), matching how `path` already works — not a DB constraint.
    comicvine_volume_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # "Följda serier" — set automatically the first time ANY user saves
    # reading progress on a book in this series (see
    # app/api/routes/reading_progress.py), never today via a manual
    # toggle. A shared, series-level flag rather than per-user: this app's
    # whole data model treats Library/Series/Book as one shared catalog
    # (ReadingProgress is the only genuinely per-user table), matching its
    # single-household deployment target rather than a multi-tenant one.
    is_following: Mapped[bool] = mapped_column(Boolean, default=False)
    followed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Filled in by the weekly release-check job (kodex.jobs.periodic +
    # app/enrichment/release_check.py) — best-effort, see that module for
    # why it can stay unfilled indefinitely for a series with no matched
    # Comic Vine/AniList id yet, or for an ebook series (no provider
    # supports a reliable "how many are published" count there).
    last_release_check_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    known_release_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_release_available: Mapped[bool] = mapped_column(Boolean, default=False)

    # B9, self-describing library — last time app/scanning/series_json.py
    # wrote a series.json companion file into this series' own folder
    # (POST /series/{id}/export). Null means never exported. THIS COLUMN
    # NEEDS A MANUAL `ALTER TABLE series ADD COLUMN metadata_exported_at
    # TIMESTAMPTZ;` ON THE PRODUCTION DATABASE — same "no Alembic yet"
    # situation as every other column added to an already-existing table
    # in this project (see claude/forbattringar-serier-samlingar.md's
    # "Driftsättning" section) — create_all() will NOT add it to an
    # existing `series` table on its own.
    metadata_exported_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Matching (kodex.matching) ---
    # The grouping key besides library_id: normalised title, start year and
    # format family ("issue", "collected", "manga", "book"). The id never
    # changes when a series is regrouped; a changed key becomes a review.
    norm_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # SeriesKey.key of the books grouped here; None for a series made by
    # hand (a split) or not yet reparsed.
    group_key: Mapped[str | None] = mapped_column(String(700), nullable=True)
    start_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    format_family: Mapped[str] = mapped_column(String(16), default="issue", server_default="issue")
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # unmatched | auto | review | manual | none (locked as "no match")
    match_status: Mapped[str] = mapped_column(String(16), default="unmatched", server_default="unmatched")
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_reason: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    matched_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Fields set by hand; automation never overwrites them.
    locked_fields: Mapped[list[str]] = mapped_column(JSON, default=list, server_default=text("'[]'"))

    library: Mapped[Library] = relationship(back_populates="series")
    books: Mapped[list[Book]] = relationship(back_populates="series", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Series id={self.id} title={self.title!r}>"
