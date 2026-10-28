from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.book import Book, visible_books
from app.models.enums import BookFormat
from app.models.library import Library
from app.models.metadata import BookMetadata
from app.models.reading_progress import ReadingProgress
from app.models.user import User
from app.progress import upstream
from app.progress.sync import apply_incoming, follow_series
from app.progress.upstream import enqueue_upstream_push
from app.schemas.reading_progress import (
    ContinueReadingItem,
    MonthCountOut,
    ProgressBulkIn,
    ReadingDayOut,
    ReadingEventOut,
    ReadingProgressIn,
    ReadingProgressOut,
    ReadingStatsOut,
)
from kodex.reading import journal, positions, stats

router = APIRouter(tags=["reading-progress"])


@router.get("/me/continue-reading", response_model=list[ContinueReadingItem])
def continue_reading(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    """The "Fortsätter läsa" shelf: books with progress between 0 and 100%
    that the user hasn't dismissed, newest first.
    """
    rows = (
        db.query(ReadingProgress, Book, BookMetadata, Library.library_type)
        .join(Book, ReadingProgress.book_id == Book.id)
        .join(Library, Book.library_id == Library.id)
        .outerjoin(BookMetadata, BookMetadata.book_id == Book.id)
        .filter(
            ReadingProgress.user_id == user.id,
            ReadingProgress.dismissed_at.is_(None),
            visible_books(),
            ReadingProgress.progress_percent > 0,
            ReadingProgress.progress_percent < 100,
        )
        .order_by(ReadingProgress.last_read_at.desc())
        .all()
    )

    return [
        {
            "book_id": book.id,
            "title": meta.title if meta else book.file_path,
            "series_id": book.series_id,
            "progress_percent": progress.progress_percent,
            "position": progress.position,
            "cover_path": meta.cover_path if meta else None,
            "last_read_at": progress.last_read_at,
            "library_type": library_type,
            "file_format": book.file_format,
            "authors": meta.authors if meta else [],
            "number": book.number,
            "edition_type": book.edition_type,
            "page_count": book.page_count,
            "pages_left": _pages_left(book, progress),
            "chapter": progress.chapter,
        }
        for progress, book, meta, library_type in rows
    ]


def _pages_left(book: Book, progress: ReadingProgress) -> int | None:
    """Pages after the one open, for paged formats (None for EPUB)."""
    if book.page_count is None or book.file_format == BookFormat.EPUB:
        return None
    index = positions.page_index(book, progress.locator_kind, progress.position, progress.progress_percent)
    return None if index is None else max(book.page_count - index - 1, 0)


@router.get("/me/reading-stats", response_model=ReadingStatsOut)
def reading_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ReadingStatsOut:
    """Books finished per month, the days something was read, streaks and
    pages, over the last year."""
    found = stats.for_user(db, user.id, dt.datetime.now(dt.UTC).date())
    return ReadingStatsOut(
        finished_total=found.finished_total,
        in_progress=found.in_progress,
        finished_by_month=[MonthCountOut(month=m, count=c) for m, c in found.finished_by_month],
        finished_by_type=found.finished_by_type,
        days=[ReadingDayOut(date=d.date, books=d.books, pages=d.pages) for d in found.days],
        current_streak=found.current_streak,
        longest_streak=found.longest_streak,
        pages=found.pages,
    )


@router.get("/books/{book_id}/progress", response_model=ReadingProgressOut | None)
def get_progress(
    book_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ReadingProgress | None:
    """Current reading position for this book, if any — used by the reader
    frontend to resume where the user left off when opening a book. Returns
    null rather than 404 when there's no progress yet: a book nobody has
    started reading is a normal state, not an error.
    """
    _pull_from_upstream(db, user, book_id)
    return (
        db.query(ReadingProgress)
        .filter(ReadingProgress.user_id == user.id, ReadingProgress.book_id == book_id)
        .one_or_none()
    )


@router.get("/books/{book_id}/journal", response_model=list[ReadingEventOut])
def get_journal(
    book_id: int,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ReadingEventOut]:
    """The user's reading journal for this book, newest first: every
    position each device reported (kodex.reading.journal)."""
    return [ReadingEventOut.model_validate(e) for e in journal.entries(db, user.id, book_id, limit)]


def _pull_from_upstream(db: Session, user: User, book_id: int) -> None:
    """With a central sync server configured (app/progress/upstream.py),
    takes its position for this book when it is newer than ours — so
    opening a book here resumes where you left off on another server or a
    KOReader device. Our own push coming back is skipped (it would swap an
    exact EPUB position for a progression). Best-effort: an unreachable
    server just means the local position is used."""
    if not upstream.is_enabled():
        return
    book = db.get(Book, book_id)
    if book is None or not book.content_hash:
        return
    remote = upstream.pull(book.content_hash)
    if remote is None or remote.get("device_id") == upstream.device_id(get_settings()):
        return
    try:
        percentage = float(remote["percentage"])
        at = dt.datetime.fromtimestamp(int(remote.get("timestamp") or 0), dt.UTC)
    except TypeError, ValueError:
        return
    local = journal.current(db, user.id, book.id)
    if local is not None and at <= local.last_read_at:
        return
    apply_incoming(db, user, book.content_hash, progress=remote.get("progress"), percentage=percentage,
                   device=remote.get("device"), device_id=remote.get("device_id"))  # fmt: skip


@router.put("/books/{book_id}/progress", response_model=ReadingProgressOut)
def save_progress(
    book_id: int,
    payload: ReadingProgressIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReadingProgress:
    """Called by the reader frontend on a debounce (every 5-10s or on page
    change / unload). Saving progress un-dismisses the book, so resuming a
    previously "removed" book naturally brings it back to the shelf.

    Also the trigger for "Följda serier" (see Series.is_following and the
    architecture plan's "Modul: Följda serier"): the first time ANY
    progress is saved on a book that belongs to a series, that whole
    series starts being checked weekly for new releases. Runs on every
    save rather than just the first, but the `is_following` guard makes
    every save after the first a no-op check, not a repeat write.
    """
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    progress, moved = journal.report(db, user.id, book, journal.Report(
        position=payload.position, locator_kind=payload.locator_kind, percent=payload.progress_percent,
        is_finished=payload.is_finished, chapter=payload.chapter, device_id=payload.device_id,
        device_name=payload.device_name, client_seq=payload.client_seq, client_at=payload.client_at))  # fmt: skip
    if moved:  # a late or repeated report is in the journal; the position stays
        follow_series(db, book)
    db.commit()
    if moved and book.content_hash:
        enqueue_upstream_push(book.id, user.id, reset=False)
    db.refresh(progress)
    return progress


@router.post("/me/progress/bulk", status_code=204, response_model=None)
def bulk_update_progress(
    payload: ProgressBulkIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> None:
    """Bulk counterpart to PUT /books/{id}/progress — "Markera som läst"/
    "Markera som oläst" over a multi-select in a grid view (see
    BulkActionBar.tsx). User-scoped like every other progress endpoint
    here, not admin-only: marking your own books read/unread is a
    personal action, same as reading a book normally would be.
    """
    books = db.query(Book).filter(Book.id.in_(payload.book_ids)).all()
    found_ids = {b.id for b in books}
    missing = set(payload.book_ids) - found_ids
    if missing:
        raise HTTPException(status_code=404, detail=f"Unknown book id(s): {sorted(missing)}")

    # Marking read or unread is the newest report, so KOReader devices
    # and other Kodex servers get it too.
    for book in books:
        percent = 100.0 if payload.is_finished else 0.0
        journal.report(db, user.id, book, journal.Report(position=None, percent=percent,
                                                          is_finished=payload.is_finished))  # fmt: skip
    db.commit()
    for book in books:
        if book.content_hash:
            enqueue_upstream_push(book.id, user.id, reset=True)


@router.post("/books/{book_id}/progress/dismiss", status_code=204, response_model=None)
def dismiss_progress(book_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    """Removes the book from the "Fortsätter läsa" shelf without resetting
    the saved position.
    """
    progress = (
        db.query(ReadingProgress)
        .filter(ReadingProgress.user_id == user.id, ReadingProgress.book_id == book_id)
        .one_or_none()
    )
    if progress is None:
        raise HTTPException(status_code=404, detail="No reading progress for this book")

    progress.dismissed_at = dt.datetime.now(dt.UTC)
    db.add(progress)
    db.commit()
