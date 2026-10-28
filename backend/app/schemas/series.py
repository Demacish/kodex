from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict


class SeriesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    library_id: int
    title: str
    path: str
    # From the match (kodex.matching): the volume's start year, publisher,
    # ongoing/ended and description; match_status is unmatched, auto,
    # confirmed, review or none.
    start_year: int | None = None
    publisher: str | None = None
    status: str | None = None
    summary: str | None = None
    match_status: str = "unmatched"
    format_family: str = "issue"
    book_count: int = 0
    cover_book_id: int | None = None
    is_matched: bool = False
    # "Följda serier" — see app/models/series.py and
    # app/enrichment/release_check.py. known_release_count/
    # last_release_check_at are None until the weekly check has actually
    # found a usable external id for this series (see that module's
    # docstring for why that can take a while, or never happen, for some
    # series).
    is_following: bool = False
    followed_at: dt.datetime | None = None
    last_release_check_at: dt.datetime | None = None
    known_release_count: int | None = None
    new_release_available: bool = False
    # B9 — last time POST /series/{id}/export wrote series.json into this
    # series' folder. Null means never exported.
    metadata_exported_at: dt.datetime | None = None
    # Per-current-user counts, computed alongside book_count in list_series
    # (see series.py's _series_out) — powers the "X/Y läst" progress badge
    # on SeriesCard.tsx. All three always sum to book_count.
    read_count: int = 0
    unread_count: int = 0
    in_progress_count: int = 0


class SeriesLetterOut(BaseModel):
    """Where a letter starts in the title-sorted series list."""

    letter: str
    offset: int
    count: int
