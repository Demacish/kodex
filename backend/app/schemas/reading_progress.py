from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import BookEditionType, BookFormat, LibraryType

LocatorKind = Literal["page", "pdf", "cfi", "xpointer", "kobo", "other", "percent"]


class ReadingProgressIn(BaseModel):
    position: str | None = None
    # What kind of locator `position` is (kodex.reading.positions); v1's
    # clients leave it out and it is inferred.
    locator_kind: LocatorKind | None = None
    progress_percent: float = Field(ge=0, le=100)
    is_finished: bool = False
    # Human-readable name of where `position` points — the EPUB reader's
    # current table-of-contents entry ("Kapitel 14"). A CFI alone can't be
    # turned back into a chapter name without opening the book, so the
    # reader sends it along. Omitted (None) by the page-based readers,
    # whose position is already a plain page number.
    chapter: str | None = Field(default=None, max_length=255)
    # Which device reports this, and its own counter (kodex.reading.journal):
    # a report with a lower counter than one already recorded is late and
    # doesn't move the position back. Optional for v1's clients.
    device_id: str | None = Field(default=None, max_length=64)
    device_name: str | None = Field(default=None, max_length=100)
    client_seq: int | None = Field(default=None, ge=0)
    client_at: dt.datetime | None = None


class ProgressBulkIn(BaseModel):
    """Body for POST /me/progress/bulk — "Markera som läst"/"Markera som
    oläst" over a multi-select, see BulkActionBar.tsx. No `position`
    field: unlike a single ReadingProgressIn save from the reader, there's
    no meaningful page position for a book someone may not have opened.
    """

    book_ids: list[int]
    is_finished: bool


class ReadingProgressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    book_id: int
    position: str | None
    locator_kind: str | None = None
    progress_percent: float
    is_finished: bool
    chapter: str | None = None
    dismissed_at: dt.datetime | None
    last_read_at: dt.datetime
    device_id: str | None = None
    device_name: str | None = None


class ReadingEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: str
    device_name: str | None
    kind: str
    position: str | None
    locator_kind: str | None = None
    progress_percent: float
    chapter: str | None
    client_at: dt.datetime | None
    received_at: dt.datetime


class ContinueReadingItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    book_id: int
    title: str
    series_id: int | None
    progress_percent: float
    position: str | None
    cover_path: str | None
    last_read_at: dt.datetime
    # Card details for the "Fortsätter läsa" shelf — type chip (from the
    # book's library), authors, issue/volume number and, for page-based
    # formats, how many pages are left.
    library_type: LibraryType
    file_format: BookFormat
    authors: list[str] = []
    number: float | None = None
    edition_type: BookEditionType = BookEditionType.ISSUE
    page_count: int | None = None
    # page_count minus the pages already read, for formats whose
    # `position` is a page (CBZ/CBR/image folder: 0-based index, PDF:
    # 1-based page number). None for EPUB (position is a CFI — see
    # `chapter` instead) or when either side is unknown.
    pages_left: int | None = None
    chapter: str | None = None


class ReadingDayOut(BaseModel):
    date: dt.date
    books: int
    pages: int


class MonthCountOut(BaseModel):
    month: str = Field(description="YYYY-MM")
    count: int


class ReadingStatsOut(BaseModel):
    """The user's reading, from the journal (kodex.reading.stats)."""

    finished_total: int
    in_progress: int
    finished_by_month: list[MonthCountOut] = Field(description="The last twelve months, oldest first.")
    finished_by_type: dict[str, int] = Field(description="Finished books by library type.")
    days: list[ReadingDayOut] = Field(description="Days something was read in the last year, with books and pages.")
    current_streak: int
    longest_streak: int
    pages: int = Field(description="Pages read in paged formats in the last year.")
