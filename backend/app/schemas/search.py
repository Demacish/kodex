from __future__ import annotations

from pydantic import BaseModel


class BookSearchHit(BaseModel):
    book_id: int
    title: str
    series_id: int | None
    series_title: str | None
    library_id: int
    library_name: str | None
    file_format: str
    cover_path: str | None


class FulltextSearchHit(BaseModel):
    book_id: int
    library_id: int
    title: str
    # A chapter href (EPUB) or page number (PDF) — the reader frontend uses
    # this to jump straight to the hit, see app/search/fulltext.py.
    position: str
    # A short excerpt around the match, as escaped HTML with the hit itself
    # wrapped in <mark></mark> (kodex.discovery.search).
    snippet: str
