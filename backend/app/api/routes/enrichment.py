"""Manual metadata matching — for when automatic enrichment (see
app/enrichment/engine.py) finds nothing or picks the wrong match. A user
searches a specific provider and picks the right result themselves.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.config import get_settings
from app.database import get_db
from app.enrichment.engine import (
    PROVIDERS,
    SELECTABLE_MATCH_FIELDS,
    apply_manual_match,
    list_issues_for_volume,
    preview_manual_match,
    provider_for_book,
    search_provider,
)
from app.models.book import Book
from app.schemas.enrichment import CandidateOut, EnrichmentActionResult, FieldDiffOut, ManualMatchIn

router = APIRouter(prefix="/books/{book_id}/enrichment", tags=["enrichment"])


def _get_book_or_404(book_id: int, db: Session) -> Book:
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


@router.get("/search", response_model=list[CandidateOut])
def search_matches(
    book_id: int,
    provider: str | None = Query(default=None, description="comicvine | anilist | open_library | google_books"),
    query: str | None = Query(default=None, description="Defaults to the book's series/title if omitted"),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
) -> list:
    """Search one provider for candidates to manually match against — used
    when automatic enrichment couldn't find (or got wrong) a match. Defaults
    to the provider the book's library type would normally use, and to the
    book's series title (or its own title) as the search query.
    """
    book = _get_book_or_404(book_id, db)
    settings = get_settings()

    chosen_provider = provider or provider_for_book(book)
    if chosen_provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider, must be one of {PROVIDERS}")

    # book_metadata.title first: it's specific to this book and engine.py
    # keeps it current on every match, unlike series.title, which used to
    # get stuck on the scanner's raw-folder-name default forever for any
    # non-comicvine provider (fixed 2026-09-17, but a book matched before
    # that fix still has a stale series.title) - falling back to the
    # book's own title here avoids that ever silently breaking this
    # search again. series.title as the second fallback still matters for
    # a comic issue whose own title is blank/generic.
    search_query = (
        query
        or (book.book_metadata.title if book.book_metadata else None)
        or (book.series.title if book.series else None)
    )
    if not search_query:
        raise HTTPException(status_code=400, detail="No query given and the book has no title to search with yet")

    if chosen_provider == "comicvine" and not settings.comicvine_api_key:
        raise HTTPException(status_code=400, detail="COMICVINE_API_KEY is not configured")

    candidates = search_provider(
        chosen_provider,
        search_query,
        api_key=settings.comicvine_api_key,
        google_books_api_key=settings.google_books_api_key,
    )
    return [
        {
            "external_id": c.external_id,
            "title": c.title,
            "year": c.year,
            "thumbnail_url": c.thumbnail_url,
            "subtitle": c.subtitle,
            "provider": chosen_provider,
        }
        for c in candidates
    ]


@router.get("/volumes/{volume_id}/issues", response_model=list[CandidateOut])
def search_volume_issues(
    book_id: int,
    volume_id: str,
    provider: str = Query(default="comicvine"),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
) -> list:
    """The second step of manual matching (F): once a volume has been
    picked from /search above, list its issues so the user can click the
    exact one instead of relying on automatic number-matching (which
    fails outright for a book whose issue number couldn't be parsed, and
    can't tell an issue apart from a same-numbered collected edition —
    see Book.edition_type). Comic Vine only, like list_issues_for_volume.
    """
    _get_book_or_404(book_id, db)  # 404s the same way every other route here does
    if provider != "comicvine":
        raise HTTPException(status_code=400, detail="Issue-level matching is only available for Comic Vine")

    settings = get_settings()
    if not settings.comicvine_api_key:
        raise HTTPException(status_code=400, detail="COMICVINE_API_KEY is not configured")

    candidates = list_issues_for_volume(provider, volume_id, settings.comicvine_api_key)
    return [
        {
            "external_id": c.external_id,
            "title": c.title,
            "year": c.year,
            "thumbnail_url": c.thumbnail_url,
            "subtitle": c.subtitle,
            "provider": "comicvine",
        }
        for c in candidates
    ]


@router.get("/preview", response_model=dict[str, FieldDiffOut])
def preview_match(
    book_id: int,
    provider: str,
    external_id: str,
    is_issue: bool = Query(default=False),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
) -> dict:
    """B8 — a side-effect-free look at what /apply would change, field by
    field, before committing to it (or to which fields to keep vs
    replace). Same provider/is_issue validation as /apply; a 404 here
    means the same as /apply returning changed=False for this candidate.
    """
    book = _get_book_or_404(book_id, db)
    if provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider, must be one of {PROVIDERS}")
    if is_issue and provider != "comicvine":
        raise HTTPException(status_code=400, detail="Issue-level matching is only available for Comic Vine")

    settings = get_settings()
    diff = preview_manual_match(
        book,
        provider,
        external_id,
        is_issue=is_issue,
        comicvine_api_key=settings.comicvine_api_key,
        google_books_api_key=settings.google_books_api_key,
    )
    if diff is None:
        raise HTTPException(status_code=404, detail="No details found for that external_id")
    return diff


@router.post("/apply", response_model=EnrichmentActionResult)
def apply_match(
    book_id: int, payload: ManualMatchIn, db: Session = Depends(get_db), _admin=Depends(require_admin)
) -> dict:
    """Apply a manually chosen candidate (a volume from /search, or —
    when payload.is_issue is set — a specific issue from
    /volumes/{volume_id}/issues above) to this book. Overwrites existing
    metadata fields with the provider's data (or, with B8's `fields` set,
    just the chosen subset) and marks the row as MANUAL, so future
    automatic re-enrichment runs leave it alone — the same protection a
    hand-typed edit would get.
    """
    book = _get_book_or_404(book_id, db)
    if payload.provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider, must be one of {PROVIDERS}")
    if payload.is_issue and payload.provider != "comicvine":
        raise HTTPException(status_code=400, detail="Issue-level matching is only available for Comic Vine")

    fields: set[str] | None = None
    if payload.fields is not None:
        fields = set(payload.fields)
        unknown = fields - SELECTABLE_MATCH_FIELDS
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown field(s): {sorted(unknown)}")

    settings = get_settings()
    changed = apply_manual_match(
        db,
        book,
        payload.provider,
        payload.external_id,
        is_issue=payload.is_issue,
        fields=fields,
        comicvine_api_key=settings.comicvine_api_key,
        google_books_api_key=settings.google_books_api_key,
        metron_username=settings.metron_username,
        metron_password=settings.metron_password,
    )
    db.commit()
    return {"changed": changed}
