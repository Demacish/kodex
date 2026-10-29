from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.enums import BookEditionType, BookFormat, MetadataSource
from app.schemas.reading_progress import ReadingProgressOut


class BookMetadataOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: str
    sort_title: str
    authors: list[str]
    genres: list[str]
    tags: list[str]
    story_arcs: list[str]
    story_arc_numbers: dict[str, float] | None
    summary: str | None
    publisher: str | None
    published_year: int | None
    language: str | None
    cover_path: str | None
    # "manual" here is what MetadataEditDialog.tsx's badge and
    # /books/{id}/enrichment's own docstring both refer to — a hand-edit
    # (this PATCH) or a confirmed provider match (enrichment/apply) both
    # set it, and both mean the same thing: auto-enrichment leaves this
    # book alone from now on.
    source: MetadataSource


class BookMetadataUpdate(BaseModel):
    """PATCH /books/{book_id} body — a hand-typed correction, the free-
    text counterpart to /books/{id}/enrichment/apply's pick-a-provider-
    candidate flow (see enrichment.py). Every field optional and only
    applied when actually present in the request body (see the route's
    `exclude_unset=True`), so leaving a field out of the PATCH — not just
    sending it null — is what means "don't touch this one". Deliberately
    excludes story_arcs/story_arc_numbers: those drive smart-collection
    membership (see kodex/collections/rules.py) and are meant to come from
    ComicInfo.xml/an enrichment provider, not a free-text edit here.

    edition_type (C) is the one field here that isn't actually a
    BookMetadata column — it lives on Book itself (see Book.edition_type's
    docstring) — but it's still the natural "hand-typed correction" this
    endpoint is for, so it rides along in the same payload rather than
    needing a separate PATCH just for one field; the route pulls it out
    before applying the rest to `meta`.
    """

    title: str | None = None
    sort_title: str | None = None
    authors: list[str] | None = None
    genres: list[str] | None = None
    tags: list[str] | None = None
    summary: str | None = None
    publisher: str | None = None
    published_year: int | None = None
    language: str | None = None
    edition_type: BookEditionType | None = None


class BookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    library_id: int
    series_id: int | None
    file_path: str
    file_format: BookFormat
    file_size: int
    page_count: int | None
    # B6 (Page Manager) — physical page indices an admin has resolved as
    # DELETED (see BookPageFlag); the reader skips these when building its
    # own page sequence (see ImageReader.tsx). Only populated on GET
    # /books/{id} — same "detail-only" scoping as `progress` below.
    deleted_page_indices: list[int] = []
    number: float | None
    edition_type: BookEditionType
    book_metadata: BookMetadataOut | None
    # Only populated by GET /books (list_books LEFT JOINs it for the
    # current user there) — GET /books/{id} leaves this null, the book
    # detail page already has its own dedicated GET .../progress call.
    progress: ReadingProgressOut | None = None
    # Non-null when the file is gone from disk and the book is hidden (see
    # Book.missing_since); only ever non-null on GET /books/{id} or the
    # admin list below, since every browsing list filters these out.
    missing_since: dt.datetime | None = None
    keep_visible_when_missing: bool = False

    @field_validator("keep_visible_when_missing", mode="before")
    @classmethod
    def _null_is_false(cls, value: object) -> object:
        """Books brought over from v1 have NULL in the column (it came late
        there); that means the same as False."""
        return False if value is None else value


class MissingBookOut(BaseModel):
    """One row of GET /books/missing — the admin "Saknade filer" view."""

    id: int
    library_id: int
    library_name: str
    series_id: int | None
    series_title: str | None
    file_path: str
    title: str
    missing_since: dt.datetime | None
    # True = an admin chose "Visa igen" while the file is still missing.
    keep_visible_when_missing: bool
