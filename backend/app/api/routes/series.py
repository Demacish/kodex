from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, case, func, or_
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.api.routes.releases import release_event_out
from app.auth import get_current_user, require_admin
from app.config import get_settings
from app.database import get_db
from app.models.book import Book, visible_books
from app.models.enums import MetadataSource
from app.models.metadata import BookMetadata
from app.models.reading_progress import ReadingProgress
from app.models.release_event import SeriesReleaseEvent
from app.models.series import Series
from app.models.user import User
from app.scanning.series_json import export_series
from app.schemas.common import JobQueuedOut
from app.schemas.release_event import ReleaseEventOut
from app.schemas.series import SeriesLetterOut, SeriesOut
from app.workers.queue import get_enrichment_queue
from app.workers.tasks import check_followed_series_task

router = APIRouter(prefix="/series", tags=["series"])

SeriesSort = Literal["title", "added_at"]
SortOrder = Literal["asc", "desc"]
ReadStatus = Literal["all", "unread", "in_progress", "read"]


def _cover_book_ids(db: Session, series_ids: list[int]) -> dict[int, int]:
    """One representative book id per series, for a cover thumbnail (see
    BookCard.tsx's existing /books/{id}/cover proxy — reused here rather
    than adding a second, series-level cover endpoint). Picks the lowest
    issue `number` (falling back to the lowest book id for books with no
    parsed number) via Postgres's DISTINCT ON — one query for every series
    on the page rather than one query per card.
    """
    if not series_ids:
        return {}
    rows = (
        db.query(Book.series_id, Book.id)
        .filter(Book.series_id.in_(series_ids), visible_books())
        .order_by(Book.series_id, Book.number.asc().nulls_last(), Book.id)
        .ext(distinct_on(Book.series_id))
        .all()
    )
    return {series_id: book_id for series_id, book_id in rows}


def _cover_book_matched(db: Session, cover_book_ids: list[int]) -> dict[int, bool]:
    """Whether each cover book's own metadata came from a real match
    (ENRICHED/MANUAL) rather than just the scanner's EMBEDDED fallback —
    the non-Comic-Vine equivalent of series.comicvine_volume_id below.
    Only meaningful for a "solo" series (see engine.py's
    _reparent_to_canonical_series): a multi-book non-comicvine series has
    no single book whose match status represents the whole series, but
    those don't exist in practice yet (AniList/Open Library/Google Books
    are all single-book-per-series so far), so this is a safe proxy today.
    """
    if not cover_book_ids:
        return {}
    rows = db.query(BookMetadata.book_id, BookMetadata.source).filter(BookMetadata.book_id.in_(cover_book_ids)).all()
    return {book_id: source != MetadataSource.EMBEDDED for book_id, source in rows}


def _series_out(
    series: Series,
    book_count: int,
    cover_book_id: int | None,
    read_count: int = 0,
    in_progress_count: int = 0,
    cover_book_matched: bool = False,
) -> dict:
    return {
        "id": series.id,
        "library_id": series.library_id,
        "title": series.title,
        "path": series.path,
        "start_year": series.start_year,
        "publisher": series.publisher,
        "status": series.status,
        "summary": series.summary,
        "match_status": series.match_status,
        "format_family": series.format_family,
        "book_count": book_count,
        "cover_book_id": cover_book_id,
        # Whether this series is grouped by a real Comic Vine match (see
        # app/enrichment/engine.py's _reparent_to_canonical_series), or —
        # for every other provider, which has no series-level match of its
        # own — whether its representative cover book has been matched
        # (see _cover_book_matched above). The "Matchad"/"Granska"
        # indicator in SeriesCard.tsx.
        "is_matched": series.comicvine_volume_id is not None or cover_book_matched,
        "is_following": series.is_following,
        "followed_at": series.followed_at,
        "last_release_check_at": series.last_release_check_at,
        "known_release_count": series.known_release_count,
        "new_release_available": series.new_release_available,
        "metadata_exported_at": series.metadata_exported_at,
        "read_count": read_count,
        "in_progress_count": in_progress_count,
        "unread_count": max(book_count - read_count - in_progress_count, 0),
    }


@router.get("", response_model=list[SeriesOut])
def list_series(
    library_id: int | None = None,
    following: bool | None = None,
    sort: SeriesSort = "title",
    order: SortOrder = "asc",
    read_status: ReadStatus = "all",
    limit: int | None = None,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """`following=true` is the "Följer"-vy's data source (see
    web/src/routes/_authed/_shell/following.tsx) — series with a new
    release sort first there, so someone following a lot of series doesn't
    have to hunt for the ones that actually changed.

    read_count/in_progress_count are joined against the *current* user's
    own ReadingProgress rows only — this app has one shared catalog but
    per-user progress (see reading_progress.py), so two users browsing the
    same library see the same books but different progress badges.
    `read_status` filters on those computed counts in HAVING, and
    `limit`/`offset` page in SQL, so a library with thousands of series
    only builds (and finds covers for) the page asked for.
    """
    own_progress = and_(ReadingProgress.book_id == Book.id, ReadingProgress.user_id == user.id)
    book_count = func.count(Book.id)
    read_count = func.coalesce(func.sum(case((ReadingProgress.is_finished.is_(True), 1), else_=0)), 0)
    in_progress_count = func.coalesce(
        func.sum(
            case(
                (
                    and_(
                        ReadingProgress.id.isnot(None),
                        ReadingProgress.is_finished.is_(False),
                        ReadingProgress.progress_percent > 0,
                    ),
                    1,
                ),
                else_=0,
            )
        ),
        0,
    )
    # The inner join leaves out a series with 0 books (e.g. every file moved
    # out by the sorting feature, or a scan that never finished): never
    # useful to show, so no caller of this endpoint needs to repeat the check.
    query = (
        db.query(Series, book_count, read_count, in_progress_count)
        .join(Book, and_(Book.series_id == Series.id, visible_books()))
        .outerjoin(ReadingProgress, own_progress)
        .group_by(Series.id)
    )
    if library_id is not None:
        query = query.filter(Series.library_id == library_id)
    if following is not None:
        query = query.filter(Series.is_following.is_(following))

    if read_status == "read":
        query = query.having(read_count == book_count)
    elif read_status == "unread":
        query = query.having(and_(read_count == 0, in_progress_count == 0))
    elif read_status == "in_progress":
        query = query.having(or_(in_progress_count > 0, and_(read_count > 0, read_count < book_count)))

    if following:
        query = query.order_by(Series.new_release_available.desc(), Series.sort_title, Series.id)
    else:
        sort_column = Series.created_at if sort == "added_at" else Series.sort_title
        query = query.order_by(sort_column.desc() if order == "desc" else sort_column.asc(), Series.id)
    if offset:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)

    rows = query.all()
    cover_book_ids = _cover_book_ids(db, [series.id for series, *_ in rows])
    cover_book_matched = _cover_book_matched(db, list(cover_book_ids.values()))
    return [
        _series_out(
            series,
            books,
            cover_book_ids.get(series.id),
            read,
            in_progress,
            cover_book_matched.get(cover_book_ids.get(series.id), False),
        )
        for series, books, read, in_progress in rows
    ]


@router.get("/letters", response_model=list[SeriesLetterOut])
def list_series_letters(
    library_id: int | None = None,
    following: bool | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[dict]:
    """Backs the alphabet jump bar (A3) on library/series listing pages —
    a cheap single-column query (just `sort_title`) rather than the full
    `GET /series` response, since the jump bar only needs where each
    letter starts, not every series' full payload. Mirrors list_series's
    `library_id`/`following` filters and its empty-series exclusion
    (`Series.books.any()`, an EXISTS — same rows list_series would show,
    just without needing the book_count/read_count aggregation it does)
    so the jump bar's counts always match what's actually on the page.
    """
    query = db.query(Series.sort_title).filter(Series.books.any(visible_books())).order_by(Series.sort_title)
    if library_id is not None:
        query = query.filter(Series.library_id == library_id)
    if following is not None:
        query = query.filter(Series.is_following.is_(following))

    letters: dict[str, dict] = {}
    for index, (sort_title,) in enumerate(query.all()):
        first_char = (sort_title or "").strip()[:1].upper()
        letter = first_char if first_char.isalpha() else "#"
        if letter not in letters:
            letters[letter] = {"letter": letter, "offset": index, "count": 0}
        letters[letter]["count"] += 1
    return list(letters.values())


@router.get("/{series_id}", response_model=SeriesOut)
def get_series(series_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    series = db.get(Series, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Series not found")

    book_count = db.query(func.count(Book.id)).filter(Book.series_id == series.id, visible_books()).scalar()
    read_count = (
        db.query(func.count(ReadingProgress.id))
        .join(Book, Book.id == ReadingProgress.book_id)
        .filter(
            Book.series_id == series.id,
            visible_books(),
            ReadingProgress.user_id == user.id,
            ReadingProgress.is_finished.is_(True),
        )
        .scalar()
    )
    in_progress_count = (
        db.query(func.count(ReadingProgress.id))
        .join(Book, Book.id == ReadingProgress.book_id)
        .filter(
            Book.series_id == series.id,
            visible_books(),
            ReadingProgress.user_id == user.id,
            ReadingProgress.is_finished.is_(False),
            ReadingProgress.progress_percent > 0,
        )
        .scalar()
    )
    cover_book_id = _cover_book_ids(db, [series.id]).get(series.id)
    cover_book_matched = _cover_book_matched(db, [cover_book_id] if cover_book_id is not None else []).get(
        cover_book_id, False
    )
    return _series_out(series, book_count, cover_book_id, read_count, in_progress_count, cover_book_matched)


@router.get("/{series_id}/release-events", response_model=list[ReleaseEventOut])
def list_series_release_events(
    series_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)
) -> list[dict]:
    """B5 — this one series' known issues (Comic Vine only, see
    release_check.py's _sync_release_events), soonest/most-recent
    store_date first. See GET /releases for the aggregated pull-list
    across every followed series.
    """
    series = db.get(Series, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Series not found")

    events = db.query(SeriesReleaseEvent).filter(SeriesReleaseEvent.series_id == series_id).all()
    items = [release_event_out(event, series_title=series.title) for event in events]
    items.sort(key=lambda item: (item["store_date"] is None, item["store_date"] or dt.date.max))
    return items


@router.post("/{series_id}/follow", response_model=SeriesOut)
def follow_series(series_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Manual follow — previously the only way a series became followed was
    implicitly, the first time reading_progress.py's save_progress saw
    progress saved on one of its books (see Series.is_following/followed_at
    there). This is the explicit counterpart for a series you want to
    watch for new releases without having started reading it yet.
    """
    series = db.get(Series, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Series not found")
    if not series.is_following:
        series.is_following = True
        series.followed_at = dt.datetime.now(dt.UTC)
        db.add(series)
        db.commit()
        db.refresh(series)

    book_count = db.query(func.count(Book.id)).filter(Book.series_id == series.id, visible_books()).scalar()
    cover_book_id = _cover_book_ids(db, [series.id]).get(series.id)
    cover_book_matched = _cover_book_matched(db, [cover_book_id] if cover_book_id is not None else []).get(
        cover_book_id, False
    )
    return _series_out(series, book_count, cover_book_id, 0, 0, cover_book_matched)


@router.post("/{series_id}/unfollow", response_model=SeriesOut)
def unfollow_series(series_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Stops future release checks/notifications for this series.
    followed_at is deliberately left as-is (not cleared) — it records when
    the series was *first* followed, which stays true/useful history even
    after unfollowing; is_following is the only field that actually gates
    app/enrichment/release_check.py's weekly check.
    """
    series = db.get(Series, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Series not found")
    if series.is_following:
        series.is_following = False
        db.add(series)
        db.commit()
        db.refresh(series)

    book_count = db.query(func.count(Book.id)).filter(Book.series_id == series.id, visible_books()).scalar()
    cover_book_id = _cover_book_ids(db, [series.id]).get(series.id)
    cover_book_matched = _cover_book_matched(db, [cover_book_id] if cover_book_id is not None else []).get(
        cover_book_id, False
    )
    return _series_out(series, book_count, cover_book_id, 0, 0, cover_book_matched)


@router.post("/check-releases", status_code=202, response_model=JobQueuedOut)
def trigger_release_check(_admin=Depends(require_admin)) -> dict:
    """Enqueue an on-demand run of the weekly followed-series release
    check — the same job kodex.jobs.periodic enqueues every Monday
    automatically once a week, exposed here so an admin doesn't have to
    wait up to seven days to see it work (or re-check right after fixing
    something, e.g. adding a missing COMICVINE_API_KEY). See
    app/enrichment/release_check.py for what the check actually does.
    """
    job = get_enrichment_queue().enqueue(check_followed_series_task, job_timeout="30m")
    return {"job_id": job.id}


@router.post("/{series_id}/export")
def export_series_json(series_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> dict:
    """B9 — writes/overwrites series.json in this series' own library
    folder (see app/scanning/series_json.py). 400 when the series has no
    books, or its books don't share one folder (see export_series).
    """
    series = db.get(Series, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Series not found")

    settings = get_settings()
    path = export_series(series, libraries_root=settings.libraries_root)
    if path is None:
        raise HTTPException(
            status_code=400, detail="Nothing to export — series has no books, or they span multiple folders"
        )

    series.metadata_exported_at = dt.datetime.now(dt.UTC)
    db.add(series)
    db.commit()
    return {"path": str(path)}
