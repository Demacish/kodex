from __future__ import annotations

import datetime as dt
import hashlib
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, contains_eager

from app.auth import get_current_user, require_admin
from app.config import get_settings
from app.database import get_db
from app.models.book import Book, visible_books
from app.models.enums import PAGE_BASED_FORMATS, MetadataSource, PageFlagResolution
from app.models.metadata import BookMetadata
from app.models.page_flag import BookPageFlag
from app.models.panel import BookPagePanel
from app.models.reading_progress import ReadingProgress
from app.models.series import Series
from app.models.user import User
from app.scanning.dimensions import CHEAP_FORMATS, cheap_page_dimensions
from app.schemas.book import BookMetadataUpdate, BookOut, MissingBookOut
from app.schemas.common import JobQueuedOut
from app.schemas.page_flag import PageFlagIn, PageFlagOut, PageFlagResolveIn
from app.workers.queue import get_delivery_queue, get_enrichment_queue, get_panel_queue
from app.workers.tasks import (
    compute_page_dimensions_task,
    detect_panels_book_task,
    enrich_book_task,
    send_to_kindle_task,
)
from kodex.formats import archive
from kodex.library.paths import OutsideLibraries, within


class PageDimensionsOut(BaseModel):
    """[width, height] per page (null for a page that couldn't be read), or
    null while unknown; ``pending`` when a job is measuring them now."""

    dimensions: list[list[int] | None] | None
    pending: bool


router = APIRouter(prefix="/books", tags=["books"])

BookSort = Literal["number", "title", "added_at", "updated_at"]
SortOrder = Literal["asc", "desc"]
ReadStatus = Literal["all", "unread", "in_progress", "read"]

_SORT_COLUMNS = {
    "number": Book.number,
    "added_at": Book.added_at,
    "updated_at": Book.updated_at,
}


def _book_out(book: Book, progress: ReadingProgress | None, *, deleted_page_indices: list[int] | None = None) -> dict:
    return {
        "id": book.id,
        "library_id": book.library_id,
        "series_id": book.series_id,
        "file_path": book.file_path,
        "file_format": book.file_format,
        "file_size": book.file_size,
        "page_count": book.page_count,
        # Only ever populated on the single-book detail response (see
        # get_book below) — list_books' rows don't bother, same reasoning
        # progress already only gets LEFT JOINed there and not here.
        "deleted_page_indices": deleted_page_indices or [],
        "number": book.number,
        "edition_type": book.edition_type,
        "book_metadata": book.book_metadata,
        "progress": progress,
        "missing_since": book.missing_since,
        "keep_visible_when_missing": bool(book.keep_visible_when_missing),
    }


@router.get("", response_model=list[BookOut])
def list_books(
    library_id: int | None = None,
    series_id: int | None = None,
    root_only: bool = False,
    following_only: bool = False,
    added_within_days: int | None = Query(default=None, ge=1, le=3650),
    sort: BookSort = "number",
    order: SortOrder = "asc",
    read_status: ReadStatus = "all",
    limit: int | None = None,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Progress is LEFT JOINed for the *current* user only (see
    reading_progress.py — this app has one shared catalog but per-user
    progress), which also lets `read_status` filter on it directly in SQL
    rather than in Python — unlike list_series's small, always-fetch-all
    result set, a single series or root-level library listing can
    genuinely be large enough (hundreds of issues) for `limit`/`offset` to
    matter, so filtering has to happen before pagination, in the database.

    `root_only` filters to series_id IS NULL (a mixed library's books with
    no series) — needed as a real filter, not a client-side post-filter,
    now that this endpoint paginates: a library/[id] page slicing "just
    the root books" out of a paginated, mixed-series page would silently
    lose books whenever a page happened to contain none.
    """
    own_progress = and_(ReadingProgress.book_id == Book.id, ReadingProgress.user_id == user.id)
    query = (
        db.query(Book, ReadingProgress)
        .outerjoin(ReadingProgress, own_progress)
        .outerjoin(BookMetadata, BookMetadata.book_id == Book.id)
        # BookMetadata is already outer-joined above (needed for sort/
        # filter) — contains_eager tells SQLAlchemy to hydrate
        # Book.book_metadata straight from those already-fetched columns
        # instead of lazy-loading it with one extra SELECT per row when
        # _book_out below reads it. Found 2026-09-21: this endpoint fires
        # twice on every homepage load (added_at/updated_at shelves,
        # limit=12 each) — 24 avoidable extra queries per home view alone.
        .options(contains_eager(Book.book_metadata))
        .filter(visible_books())
    )
    if library_id is not None:
        query = query.filter(Book.library_id == library_id)
    if series_id is not None:
        query = query.filter(Book.series_id == series_id)
    if root_only:
        query = query.filter(Book.series_id.is_(None))
    # The home page's "Nytt i serier du följer" shelf: recent additions to
    # followed series (see Series.is_following), usually with
    # read_status=unread.
    if following_only:
        query = query.filter(Book.series.has(Series.is_following.is_(True)))
    if added_within_days is not None:
        since = dt.datetime.now(dt.UTC) - dt.timedelta(days=added_within_days)
        query = query.filter(Book.added_at >= since)

    if read_status == "read":
        query = query.filter(ReadingProgress.is_finished.is_(True))
    elif read_status == "in_progress":
        query = query.filter(
            ReadingProgress.id.isnot(None), ReadingProgress.is_finished.is_(False), ReadingProgress.progress_percent > 0
        )
    elif read_status == "unread":
        query = query.filter(
            or_(
                ReadingProgress.id.is_(None),
                and_(ReadingProgress.is_finished.is_(False), ReadingProgress.progress_percent == 0),
            )
        )

    if sort == "title":
        sort_column = func.coalesce(BookMetadata.sort_title, Book.file_path)
    else:
        sort_column = _SORT_COLUMNS[sort]
    query = query.order_by(sort_column.desc() if order == "desc" else sort_column.asc(), Book.file_path)

    if limit is not None:
        query = query.limit(limit).offset(offset)
    elif offset:
        query = query.offset(offset)

    return [_book_out(book, progress) for book, progress in query.all()]


@router.get("/missing", response_model=list[MissingBookOut])
def list_missing_books(db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> list[dict]:
    """Books whose file a scan couldn't find: hidden ones (missing_since
    set) and ones an admin chose to keep showing anyway. Newest first.
    Declared before /{book_id} so "missing" isn't parsed as an id.
    """
    books = (
        db.query(Book)
        .filter(or_(Book.missing_since.isnot(None), Book.keep_visible_when_missing.is_(True)))
        .order_by(Book.missing_since.desc().nulls_last(), Book.file_path)
        .all()
    )
    return [
        {
            "id": book.id,
            "library_id": book.library_id,
            "library_name": book.library.name,
            "series_id": book.series_id,
            "series_title": book.series.title if book.series else None,
            "file_path": book.file_path,
            "title": book.book_metadata.title if book.book_metadata else book.file_path,
            "missing_since": book.missing_since,
            "keep_visible_when_missing": bool(book.keep_visible_when_missing),
        }
        for book in books
    ]


def _get_book_or_404(book_id: int, db: Session) -> Book:
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


def _absolute_path(book: Book) -> Path:
    settings = get_settings()
    try:
        return within(settings.libraries_root, book.library.path, book.file_path)
    except OutsideLibraries as exc:
        raise HTTPException(status_code=404, detail="Book not found") from exc


@router.get("/{book_id}", response_model=BookOut)
def get_book(book_id: int, db: Session = Depends(get_db), _user=Depends(get_current_user)) -> dict:
    book = _get_book_or_404(book_id, db)
    deleted_page_indices = sorted(
        row[0]
        for row in db.query(BookPageFlag.page_index)
        .filter(BookPageFlag.book_id == book_id, BookPageFlag.resolved_action == PageFlagResolution.DELETED)
        .all()
    )
    return _book_out(book, None, deleted_page_indices=deleted_page_indices)


@router.post("/{book_id}/restore", response_model=BookOut)
def restore_missing_book(book_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> dict:
    """ "Visa igen": shows a book hidden because its file is missing, and
    keeps showing it on later scans until the file turns up again (then it
    goes back to hiding normally if it ever disappears). A no-op for a
    book that isn't hidden."""
    book = _get_book_or_404(book_id, db)
    if book.missing_since is not None:
        book.missing_since = None
        book.keep_visible_when_missing = True
        db.add(book)
        db.commit()
        db.refresh(book)
    return _book_out(book, None)


@router.post("/{book_id}/hide", response_model=BookOut)
def hide_missing_book(book_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> dict:
    """Undoes "Visa igen" for a book whose file is still missing — hides it
    again right away instead of waiting for the next scan. Only allowed
    for books an admin restored by hand (keep_visible_when_missing): any
    other book's visibility is the scanner's call, based on whether its
    file is actually there."""
    book = _get_book_or_404(book_id, db)
    if not book.keep_visible_when_missing:
        raise HTTPException(status_code=409, detail="Only a book restored with 'Visa igen' can be hidden again")
    book.keep_visible_when_missing = False
    book.missing_since = dt.datetime.now(dt.UTC)
    db.add(book)
    db.commit()
    db.refresh(book)
    return _book_out(book, None)


@router.patch("/{book_id}", response_model=BookOut)
def update_book_metadata(
    book_id: int, payload: BookMetadataUpdate, db: Session = Depends(get_db), _admin=Depends(require_admin)
) -> Book:
    """Hand-typed metadata correction — MetadataEditDialog.tsx's save
    action, the free-text counterpart to /enrichment/apply's pick-a-
    candidate flow. Only fields actually present in the request body are
    touched (exclude_unset, not "is it null") and the row is marked
    MANUAL same as a confirmed provider match — see
    app/enrichment/engine.py's _apply_result docstring: "A row already
    matched by the user (source=MANUAL) never reaches this function in
    the first place", i.e. this is the exact same protection, not a
    parallel mechanism.
    """
    book = _get_book_or_404(book_id, db)
    fields = payload.model_dump(exclude_unset=True)

    # Book.edition_type, not a BookMetadata column — see
    # BookMetadataUpdate's own docstring for why it still rides along in
    # this same payload. Popped out before the "anything left to apply"
    # check below so an edition_type-only PATCH doesn't create a
    # BookMetadata row or mark it MANUAL — that field's own manual/auto
    # distinction is independent of the descriptive-metadata one.
    if "edition_type" in fields:
        book.edition_type = fields.pop("edition_type")

    if fields:
        meta = book.book_metadata
        if meta is None:
            # Scanning always creates a book_metadata row (see scanner.py) —
            # this is defensive, not an expected path.
            meta = BookMetadata(book_id=book.id, title=fields.get("title") or book.file_path, sort_title="")
            book.book_metadata = meta

        for attr, value in fields.items():
            setattr(meta, attr, value)
        meta.source = MetadataSource.MANUAL

    db.commit()
    db.refresh(book)
    return book


@router.get("/{book_id}/file")
def download_book_file(book_id: int, db: Session = Depends(get_db), _user=Depends(get_current_user)) -> FileResponse:
    """Serves the raw file — used directly by EPUB/PDF readers (epub.js and
    pdf.js both fetch the whole file) and by Send-to-Device. CBZ/CBR paging
    for the image reader instead goes through /pages/{n}.
    """
    book = _get_book_or_404(book_id, db)
    path = _absolute_path(book)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File missing on disk — try rescanning the library")
    return FileResponse(path)


class FileDigestOut(BaseModel):
    sha256: str
    size: int


@router.get("/{book_id}/digest", response_model=FileDigestOut)
def file_digest(book_id: int, db: Session = Depends(get_db), _user=Depends(get_current_user)) -> FileDigestOut:
    """The file's SHA-256 and size, for an app verifying a download (and
    resuming one with Range on /file). Taken on the first ask, then kept
    until the file changes."""
    from kodex.library import digest

    book = _get_book_or_404(book_id, db)
    path = _absolute_path(book)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File missing on disk — try rescanning the library")
    sha = digest.sha256(book, path)
    db.commit()
    return FileDigestOut(sha256=sha, size=path.stat().st_size)


@router.get("/{book_id}/pages/dimensions", response_model=PageDimensionsOut)
def get_page_dimensions(book_id: int, db: Session = Depends(get_db), _user=Depends(get_current_user)) -> dict:
    """[width, height] per page for the image reader (see
    app/scanning/dimensions.py). `dimensions` is null while unknown: a CBR
    is sized by a background job the first time this is asked for
    (`pending` true), so the reader just works without sizes that once.
    Declared before /pages/{page_index} so "dimensions" isn't parsed as
    a page number."""
    book = _get_book_or_404(book_id, db)
    if book.file_format not in PAGE_BASED_FORMATS:
        raise HTTPException(status_code=400, detail="This book format is not page-based")
    if book.page_dimensions is not None:
        return {"dimensions": book.page_dimensions, "pending": False}

    if book.file_format in CHEAP_FORMATS:
        try:
            book.page_dimensions = cheap_page_dimensions(_absolute_path(book), book.file_format)
        except Exception:  # noqa: BLE001 - a missing/broken file just means no sizes
            return {"dimensions": None, "pending": False}
        db.add(book)
        db.commit()
        return {"dimensions": book.page_dimensions, "pending": False}

    try:
        get_panel_queue().enqueue(
            compute_page_dimensions_task, book.id, job_id=f"page-dimensions-{book.id}", job_timeout="30m"
        )
    except Exception:  # noqa: BLE001 - no worker/Redis: the reader works without sizes
        return {"dimensions": None, "pending": False}
    return {"dimensions": None, "pending": True}


@router.get("/{book_id}/pages/{page_index}", response_class=Response,
            responses={200: {"content": {"image/webp": {}, "image/jpeg": {}, "image/png": {}}}})  # fmt: skip
def get_book_page(
    book_id: int,
    page_index: int,
    request: Request,
    max_width: int | None = Query(None, ge=64, le=8192, description="Re-encode to WebP at most this wide"),
    trim: bool = Query(False, description="Cut blank margins (re-encodes to WebP)"),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
) -> Response:
    """One page of a CBZ/CBR/CB7/image-folder book: as stored, or as WebP
    when it is narrowed, trimmed or in a format browsers can't show
    (kodex.reading.pages)."""
    from kodex.reading import pages

    book = _get_book_or_404(book_id, db)
    if book.file_format not in PAGE_BASED_FORMATS:
        raise HTTPException(status_code=400, detail="This book format is not page-based")
    path = _absolute_path(book)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk — try rescanning the library")
    tag = pages.etag(book, path, page_index, max_width=max_width, trim=trim)
    headers = {"ETag": tag, "Cache-Control": "private, max-age=86400"}
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers=headers)
    try:
        found = pages.page(book, path, page_index, get_settings().covers_dir / "pages",
                           max_width=max_width, trim=trim)  # fmt: skip
    except IndexError as exc:
        raise HTTPException(status_code=404, detail="Page out of range") from exc
    except archive.ArchiveError as exc:
        raise HTTPException(status_code=422, detail=f"Unreadable page: {exc}") from exc
    return Response(found.data, media_type=found.media_type, headers=headers)


@router.get("/{book_id}/pages/{page_index}/panels")
def get_page_panels(
    book_id: int, page_index: int, db: Session = Depends(get_db), _user=Depends(get_current_user)
) -> list[dict]:
    """Guided View panel boxes for one page — normalized (0..1) x/y/w/h in
    reading order, see app/models/panel.py. Always an empty list (never a
    404) when there's nothing to guide through: no detection has run yet,
    detection found this page "not panel-able" (see app/panels/detector.py),
    or settings.guided_view_enabled is off — the frontend's fallback is
    identical in all three cases (show the full page), so it doesn't need
    to tell them apart.
    """
    settings = get_settings()
    if not settings.guided_view_enabled:
        return []

    _get_book_or_404(book_id, db)
    panels = (
        db.query(BookPagePanel)
        .filter(BookPagePanel.book_id == book_id, BookPagePanel.page_index == page_index)
        .order_by(BookPagePanel.order_index)
        .all()
    )
    return [{"x": p.x, "y": p.y, "w": p.w, "h": p.h} for p in panels]


@router.post("/{book_id}/pages/{page_index}/flag", response_model=PageFlagOut, status_code=201)
def flag_page(
    book_id: int,
    page_index: int,
    payload: PageFlagIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BookPageFlag:
    """B6 (Page Manager) — any logged-in reader can flag a page (scanner
    junk, a duplicate, corrupt). Idempotent: re-flagging a page that
    already has an unresolved flag just returns the existing one (updating
    reason/note) rather than erroring — a reader clicking the flag button
    twice, or two readers flagging the same bad page, shouldn't 409.
    A page with a *resolved* flag can be flagged again (e.g. an admin
    "kept" it, but wants to revisit later — see the unique constraint,
    which the DELETE endpoint below clears at resolve time... actually see
    that route: resolving does not delete the row, so re-flagging instead
    reopens it).
    """
    _get_book_or_404(book_id, db)
    existing = (
        db.query(BookPageFlag)
        .filter(BookPageFlag.book_id == book_id, BookPageFlag.page_index == page_index)
        .one_or_none()
    )
    if existing is not None:
        existing.reason = payload.reason
        existing.note = payload.note
        existing.flagged_by_user_id = user.id
        # Reopens a previously resolved flag — see this route's docstring.
        existing.resolved = False
        existing.resolved_action = None
        existing.resolved_at = None
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    flag = BookPageFlag(
        book_id=book_id, page_index=page_index, reason=payload.reason, note=payload.note, flagged_by_user_id=user.id
    )
    db.add(flag)
    db.commit()
    db.refresh(flag)
    return flag


@router.delete("/{book_id}/pages/{page_index}/flag", status_code=204, response_model=None)
def unflag_page(
    book_id: int, page_index: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> None:
    """Withdraws a flag — the flagging reader themselves, or any admin,
    can do this (same "own it or be an admin" scoping as removing a book
    from a manual collection isn't — this is closer to withdrawing your
    own request). A flag someone else already resolved (see /resolve) is
    left alone; use /resolve to change a verdict instead.
    """
    flag = (
        db.query(BookPageFlag)
        .filter(BookPageFlag.book_id == book_id, BookPageFlag.page_index == page_index)
        .one_or_none()
    )
    if flag is None:
        return
    if flag.flagged_by_user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Only the reporting user or an admin can remove this flag")
    db.delete(flag)
    db.commit()


@router.post("/{book_id}/pages/{page_index}/resolve", response_model=PageFlagOut)
def resolve_page_flag(
    book_id: int,
    page_index: int,
    payload: PageFlagResolveIn,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> BookPageFlag:
    """Admin verdict on a flagged page — DELETED hides it from every
    reader from now on (see Book.deleted_page_indices, computed in
    _book_out_detail below); KEPT just closes the flag out with no
    reader-facing effect. Never touches the source archive file — see
    BookPageFlag's own docstring.
    """
    flag = (
        db.query(BookPageFlag)
        .filter(BookPageFlag.book_id == book_id, BookPageFlag.page_index == page_index)
        .one_or_none()
    )
    if flag is None:
        raise HTTPException(status_code=404, detail="No flag for that page")

    flag.resolved = True
    flag.resolved_action = payload.action
    flag.resolved_at = dt.datetime.now(dt.UTC)
    db.add(flag)
    db.commit()
    db.refresh(flag)
    return flag


def _stat_etag(path: Path) -> str:
    """Same weak-etag formula Starlette's FileResponse.set_stat_headers
    already uses (mtime+size, md5'd) — kept in sync so a client that cached
    the ETag from one response still gets a clean 304 from the other path.
    """
    stat_result = path.stat()
    etag_base = f"{stat_result.st_mtime}-{stat_result.st_size}"
    return f'"{hashlib.md5(etag_base.encode(), usedforsecurity=False).hexdigest()}"'


def _generated_cover(book: Book, size: str, settings, db: Session) -> Path | None:
    """The book's cover in one of kodex.library.covers' sizes, made now if
    the background job hasn't made it yet (or the source changed)."""
    from kodex.library import covers

    path = covers.cover_file(settings.covers_dir, book.id, size)
    if book.cover_key and path.is_file():
        return path
    try:
        covers.make(book, settings.libraries_root, settings.covers_dir, force=True)
        db.commit()
    except Exception:
        db.rollback()
        logging.getLogger(__name__).exception("Could not make covers for book %s", book.id)
        return None
    return path if path.is_file() else None


@router.get("/{book_id}/cover")
def get_cover(
    book_id: int,
    request: Request,
    thumb: bool = Query(False, description="Same as size=medium"),
    size: Literal["small", "medium", "large"] | None = Query(
        None, description="200, 400 or 1000 px on the long edge, as WebP"
    ),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> Response:
    """Serves the book's cover. With a size, one of the generated WebP
    sizes; without one, the downloaded original if there is one, else the
    book's own first page for page-based formats, so the UI always has
    something to show.
    """
    book = _get_book_or_404(book_id, db)
    settings = get_settings()
    wanted = size or ("medium" if thumb else None)
    if wanted is not None and (generated := _generated_cover(book, wanted, settings, db)) is not None:
        etag = _stat_etag(generated)
        headers = {"ETag": etag, "Cache-Control": "private, max-age=86400, must-revalidate"}
        if_none_match = request.headers.get("if-none-match")
        if if_none_match and etag in {tag.strip() for tag in if_none_match.split(",")}:
            return Response(status_code=304, headers=headers)
        return FileResponse(generated, media_type="image/webp", headers=headers)

    if book.book_metadata and book.book_metadata.cover_path:
        cover_path = settings.covers_dir / book.book_metadata.cover_path
        if cover_path.is_file():
            # The original (a size that couldn't be made falls back here too).
            serve_path = cover_path
            media_type = None
            # Covers rarely change (only on a re-match/re-enrich), but this
            # endpoint had no caching at all - the browser re-requested
            # (and this route re-did a DB lookup for) every cover on every
            # single library page load, which is what made opening a
            # library with 100+ books noticeably slow. A day's caching is
            # a reasonable staleness trade-off for a personal library.
            # FileResponse computes the same ETag Starlette always has
            # (mtime+size, see _stat_etag above) but never actually checks
            # it against the request — every hit re-sent the full body even
            # when the browser already had it cached. Checking If-None-Match
            # ourselves and short-circuiting to a bodyless 304 is what
            # actually turns a next-day reload into a handful of 304s
            # instead of re-downloading every cover (see Omnibus's "Covers
            # Load Light & Cache Hard" for the same idea).
            etag = _stat_etag(serve_path)
            cache_headers = {"ETag": etag, "Cache-Control": "private, max-age=86400, must-revalidate"}
            if_none_match = request.headers.get("if-none-match")
            if if_none_match and etag in {tag.strip() for tag in if_none_match.split(",")}:
                return Response(status_code=304, headers=cache_headers)
            return FileResponse(serve_path, media_type=media_type, headers=cache_headers)

    if book.file_format in PAGE_BASED_FORMATS:
        return get_book_page(book_id, 0, db, user)

    raise HTTPException(status_code=404, detail="No cover available for this book")


@router.post("/{book_id}/enrich", status_code=202, response_model=JobQueuedOut)
def trigger_book_enrichment(
    book_id: int, force: bool = True, db: Session = Depends(get_db), _admin=Depends(require_admin)
) -> dict:
    """Re-run automatic enrichment for a single book. Defaults to
    force=True (unlike the library-wide job) since a single-book trigger
    is normally someone deliberately asking to redo it — pass force=false
    to only fill in what's still blank instead. Has no effect on a book
    whose metadata is marked MANUAL; use /enrichment/apply to change those.
    """
    book = _get_book_or_404(book_id, db)
    # Same "RQ's 180s default kills a job that's correctly waiting out
    # Comic Vine's shared 200/hour quota" reason as enrich_library_task's
    # own job_timeout="12h" (see trigger_enrichment in libraries.py) —
    # a single book only makes a handful of calls, but if the quota's
    # already exhausted by other activity, comicvine_limiter.acquire()
    # can legitimately block for most of an hour, and 180s isn't enough
    # to survive that wait. Missed here originally; found 2026-09-21.
    job = get_enrichment_queue().enqueue(enrich_book_task, book.id, force, job_timeout="1h")
    return {"job_id": job.id}


@router.post("/{book_id}/detect-panels", status_code=202, response_model=JobQueuedOut)
def trigger_book_panel_detection(
    book_id: int, force: bool = True, db: Session = Depends(get_db), _admin=Depends(require_admin)
) -> dict:
    """(Re-)run Guided View panel detection for a single book. Defaults to
    force=True, same reasoning as /enrich above — a single-book trigger is
    normally a deliberate re-do. Returns 202 even if guided_view_enabled is
    off; the job itself is a fast no-op in that case (see
    app/panels/service.py) rather than something worth rejecting here.
    """
    book = _get_book_or_404(book_id, db)
    job = get_panel_queue().enqueue(detect_panels_book_task, book.id, force)
    return {"job_id": job.id}


@router.post("/{book_id}/send-to-kindle", status_code=202, response_model=JobQueuedOut)
def send_book_to_kindle_endpoint(
    book_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """Enqueues a Send-to-Device job for the current user's own Kindle
    address (see kodex/delivery/kindle.py). 400s immediately, before
    touching the queue, if there's nothing to send to — a missing address
    is something the user fixes in their own settings, not worth a round
    trip through the worker to discover.
    """
    book = _get_book_or_404(book_id, db)
    if not user.kindle_email:
        raise HTTPException(
            status_code=400, detail="Ingen Kindle-adress är inställd — lägg till en under Inställningar"
        )

    job = get_delivery_queue().enqueue(send_to_kindle_task, book.id, user.id)
    return {"job_id": job.id}
