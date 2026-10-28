"""The matching API (admin only): the review queue and its actions, manual
search, matching jobs, and the series actions merge, split and move.

The queue is grouped per series and sorted by how many books an item
affects. Every decision can be undone: an automatic one by reverting it,
a person's (including bulk ones) by reopening it.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models.book import Book
from app.models.library import Library
from app.models.series import Series
from app.models.user import User
from app.schemas.common import JobQueuedOut
from kodex.matching import engine as matching
from kodex.matching.models import MatchReview
from kodex.matching.providers.base import ProviderError, RateLimited
from kodex.matching.score import score_candidate
from kodex.matching.series_ops import accept_regroup, merge_series, move_books, reject_regroup, split_series

router = APIRouter(prefix="/matching", tags=["matching"])


class MatchCandidateOut(BaseModel):
    """A provider's run (volume, manga, book) scored against a series: the
    score, each signal's part of it, and why it can't win if it can't."""

    provider: str
    id: str
    name: str
    start_year: int | None = None
    publisher: str | None = None
    issue_count: int | None = None
    cover_url: str | None = None
    url: str | None = None
    links: dict[str, str] = {}
    score: float
    signals: dict[str, float] = {}
    details: dict[str, Any] = {}
    positive: list[str] = []
    disqualified: str | None = None


class ReviewOut(BaseModel):
    id: int
    kind: str
    status: str
    library_id: int
    series_id: int | None
    book_id: int | None
    title: str
    book_count: int
    best_score: float | None
    parsed: dict[str, Any] | None
    candidates: list[MatchCandidateOut]
    suggestion: dict[str, Any] | None
    decision: dict[str, Any] | None
    created_at: dt.datetime
    decided_at: dt.datetime | None

    model_config = {"from_attributes": True}


class ReviewPage(BaseModel):
    items: list[ReviewOut]
    total: int
    counts: dict[str, int]


class ChooseIn(BaseModel):
    provider: str
    id: str


class SearchIn(BaseModel):
    query: str = Field(min_length=1)
    provider: str | None = None


class BulkIn(BaseModel):
    review_ids: list[int] = Field(min_length=1, max_length=200)
    action: Literal["accept_best", "no_match", "dismiss"]


class BulkOut(BaseModel):
    done: list[int]
    failed: list[dict[str, Any]]


class SeriesIdOut(BaseModel):
    series_id: int


class MovedOut(BaseModel):
    moved: int


class SplitIn(BaseModel):
    book_ids: list[int] = Field(min_length=1)
    title: str = Field(min_length=1)


class MergeIn(BaseModel):
    source_series_ids: list[int] = Field(min_length=1)


class MoveIn(BaseModel):
    book_ids: list[int] = Field(min_length=1)
    target_series_id: int


def _review(db: Session, review_id: int) -> MatchReview:
    review = db.get(MatchReview, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


def _matcher(db: Session, review: MatchReview) -> matching.Matcher:
    library = db.get(Library, review.library_id)
    assert library is not None
    return matching.Matcher(db, matching.build_providers(db.get_bind(), matching.library_kind(library)))  # type: ignore[arg-type]


def _provider_error(exc: ProviderError) -> HTTPException:
    if isinstance(exc, RateLimited):
        return HTTPException(status_code=429, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


@router.get("/reviews", response_model=ReviewPage)
def list_reviews(
    status: str = "open",
    kind: str | None = None,
    library_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ReviewPage:
    query = select(MatchReview).where(MatchReview.status == status)
    if kind:
        query = query.where(MatchReview.kind == kind)
    if library_id is not None:
        query = query.where(MatchReview.library_id == library_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(
        query.order_by(MatchReview.book_count.desc(), MatchReview.best_score.desc().nulls_last(), MatchReview.id)
        .limit(min(limit, 200))
        .offset(offset)
    ).all()
    counts = dict(db.execute(select(MatchReview.status, func.count()).group_by(MatchReview.status)).tuples().all())
    return ReviewPage(items=[ReviewOut.model_validate(r) for r in items], total=total, counts=counts)


@router.get("/reviews/{review_id}", response_model=ReviewOut)
def get_review(review_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> MatchReview:
    return _review(db, review_id)


@router.post("/reviews/{review_id}/choose", response_model=ReviewOut)
def choose(
    review_id: int, body: ChooseIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> MatchReview:
    review = _review(db, review_id)
    if review.kind not in ("series_match", "book_match") or review.status != "open":
        raise HTTPException(status_code=409, detail="Only open matches can be chosen")
    matcher = _matcher(db, review)
    try:
        matching.choose_candidate(db, review, matcher, body.provider, body.id, user_id=admin.id)
    except ProviderError as exc:
        db.rollback()
        raise _provider_error(exc) from exc
    finally:
        matcher.providers.close()
    db.commit()
    return review


@router.post("/reviews/{review_id}/no-match", response_model=ReviewOut)
def no_match(review_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> MatchReview:
    review = _review(db, review_id)
    if review.kind != "series_match" or review.status != "open":
        raise HTTPException(status_code=409, detail="Only open series matches can be marked")
    matching.mark_no_match(db, review, user_id=admin.id)
    db.commit()
    return review


@router.post("/reviews/{review_id}/revert", response_model=ReviewOut)
def revert(review_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> MatchReview:
    review = _review(db, review_id)
    try:
        if review.status == "auto":
            matching.revert_auto(db, review, user_id=admin.id)
        else:
            matching.reopen(db, review, user_id=admin.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return review


@router.post("/reviews/{review_id}/regroup", response_model=ReviewOut)
def regroup(
    review_id: int, accept: bool, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> MatchReview:
    review = _review(db, review_id)
    if review.kind != "regroup" or review.status != "open":
        raise HTTPException(status_code=409, detail="Not an open regroup proposal")
    (accept_regroup if accept else reject_regroup)(db, review, user_id=admin.id)
    db.commit()
    return review


@router.post("/reviews/{review_id}/dismiss", response_model=ReviewOut)
def dismiss(review_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> MatchReview:
    review = _review(db, review_id)
    if review.status != "open":
        raise HTTPException(status_code=409, detail="Not open")
    review.status = "dismissed"
    review.decision = {"action": "dismiss"}
    review.decided_by_user_id = admin.id
    review.decided_at = dt.datetime.now(dt.UTC)
    db.commit()
    return review


@router.post("/reviews/{review_id}/search", response_model=list[MatchCandidateOut])
def search(
    review_id: int, body: SearchIn, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> list[dict[str, Any]]:
    """Searches with another title (or one provider) and returns scored
    candidates; nothing is applied."""
    review = _review(db, review_id)
    series = db.get(Series, review.series_id) if review.series_id else None
    if series is None:
        raise HTTPException(status_code=404, detail="Series not found")
    matcher = _matcher(db, review)
    try:
        context = matching.gather(db, series, libraries_root=matcher.libraries_root)
        names = [body.provider] if body.provider else matcher._order(context.kind)
        results = []
        for name in names:
            client = matcher.providers.get(name)
            if client is None:
                continue
            for run in client.search_runs(body.query)[:15]:
                results.append(score_candidate(context.evidence, run, matcher.config).as_dict())
    except ProviderError as exc:
        raise _provider_error(exc) from exc
    finally:
        matcher.providers.close()
    return sorted(results, key=lambda c: c["score"], reverse=True)[:20]


@router.post("/reviews/bulk", response_model=BulkOut)
def bulk(body: BulkIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict[str, Any]:
    """Accepts the best candidate of, or marks "no match" on, several open
    reviews at once. Each can be undone with /revert (which reopens it)."""
    done, failed = [], []
    providers_by_library: dict[int, matching.Matcher] = {}
    try:
        for review_id in body.review_ids:
            review = db.get(MatchReview, review_id)
            if review is None or review.status != "open":
                failed.append({"id": review_id, "error": "not open"})
                continue
            try:
                if body.action == "dismiss":
                    review.status, review.decision = "dismissed", {"action": "dismiss"}
                elif body.action == "no_match":
                    matching.mark_no_match(db, review, user_id=admin.id)
                else:
                    if not review.candidates:
                        failed.append({"id": review_id, "error": "no candidates"})
                        continue
                    if review.library_id not in providers_by_library:
                        providers_by_library[review.library_id] = _matcher(db, review)
                    best = review.candidates[0]
                    matching.choose_candidate(db, review, providers_by_library[review.library_id], best["provider"], best["id"],
                                              user_id=admin.id)  # fmt: skip
                db.commit()
                done.append(review_id)
            except (ProviderError, ValueError) as exc:
                db.rollback()
                failed.append({"id": review_id, "error": str(exc)})
                if isinstance(exc, RateLimited):
                    break
    finally:
        for matcher in providers_by_library.values():
            matcher.providers.close()
    return {"done": done, "failed": failed}


@router.post("/libraries/{library_id}/match", status_code=202, response_model=JobQueuedOut)
def match_library(
    library_id: int, force: bool = False, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict[str, Any]:
    from app.workers.queue import get_enrichment_queue
    from app.workers.tasks import match_library_task

    if db.get(Library, library_id) is None:
        raise HTTPException(status_code=404, detail="Library not found")
    job = get_enrichment_queue().enqueue(match_library_task, library_id, force, job_timeout="6h")
    return {"job_id": job.id}


@router.post("/series/{series_id}/match", status_code=202, response_model=JobQueuedOut)
def match_series(
    series_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict[str, Any]:
    from app.workers.queue import get_enrichment_queue
    from app.workers.tasks import match_series_task

    if db.get(Series, series_id) is None:
        raise HTTPException(status_code=404, detail="Series not found")
    job = get_enrichment_queue().enqueue(match_series_task, series_id, job_timeout="30m")
    return {"job_id": job.id}


@router.post("/series/{series_id}/split", response_model=SeriesIdOut)
def split(
    series_id: int, body: SplitIn, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict[str, Any]:
    series = db.get(Series, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Series not found")
    owned = set(db.scalars(select(Book.id).where(Book.series_id == series_id, Book.id.in_(body.book_ids))))
    if owned != set(body.book_ids):
        raise HTTPException(status_code=400, detail="Every book must belong to the series")
    new = split_series(db, series, body.book_ids, body.title)
    db.commit()
    return {"series_id": new.id}


@router.post("/series/{series_id}/merge", response_model=SeriesIdOut)
def merge(
    series_id: int, body: MergeIn, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict[str, Any]:
    target = db.get(Series, series_id)
    sources = [db.get(Series, sid) for sid in body.source_series_ids]
    if target is None or any(s is None for s in sources):
        raise HTTPException(status_code=404, detail="Series not found")
    if any(s.library_id != target.library_id for s in sources if s is not None):
        raise HTTPException(status_code=400, detail="Series must be in the same library")
    merge_series(db, target, [s for s in sources if s is not None])
    db.commit()
    return {"series_id": target.id}


@router.post("/books/move", response_model=MovedOut)
def move(body: MoveIn, db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> dict[str, Any]:
    target = db.get(Series, body.target_series_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Series not found")
    libraries = set(db.scalars(select(Book.library_id).where(Book.id.in_(body.book_ids))))
    if libraries != {target.library_id}:
        raise HTTPException(status_code=400, detail="Books and series must be in the same library")
    move_books(db, body.book_ids, target, lock=True)
    db.commit()
    return {"moved": len(body.book_ids)}
