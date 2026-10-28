"""Search endpoints, in PostgreSQL (kodex.discovery.search). Two scopes
rather than one endpoint with a mode flag, since the result shapes differ:
a metadata hit is a book, a fulltext hit is a chapter/page *within* a
book, with a snippet and a jump-to-hit position.

Metadata search reads the books as they are, so it is always up to date.
Fulltext search only finds text in libraries where someone has run
POST /libraries/{id}/fulltext-index — see app/search/fulltext.py for why
that stays a manual, per-library job.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.schemas.search import BookSearchHit, FulltextSearchHit
from kodex.discovery import search

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/books", response_model=list[BookSearchHit])
def search_books(
    q: str = Query(max_length=200),
    library_id: int | None = None,
    series_id: int | None = None,
    limit: int = Query(default=30, le=100),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
) -> list[dict]:
    return [asdict(hit) for hit in search.books(db, q, library_id=library_id, series_id=series_id, limit=limit)]


@router.get("/fulltext", response_model=list[FulltextSearchHit])
def search_fulltext(
    q: str = Query(max_length=200),
    book_id: int | None = None,
    library_id: int | None = None,
    limit: int = Query(default=30, le=100),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
) -> list[dict]:
    """The snippet is escaped HTML with the hit in <mark></mark>."""
    return [asdict(hit) for hit in search.fulltext(db, q, book_id=book_id, library_id=library_id, limit=limit)]
