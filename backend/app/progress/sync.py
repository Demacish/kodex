"""Shared rules for syncing reading progress between devices and servers
over the KOSync protocol (KOReader, Kobo devices with KOReader, and other
Kodex servers, see app/progress/upstream.py).

Identity: a book's content_hash (KOReader's "binary" document id, a
partial MD5, see app/scanning/fingerprint.py), and the ids its file had
before, so the same file is the same book on every Kodex server and every
device.

Conflicts: the newest report wins, as on KOReader's own sync server. Every
report goes through the reading journal (kodex.reading.journal) like the
web reader's, so the history shows which device read what.

Positions: a KOReader page is a page index plus one; an EPUB position is
KOReader's own XPointer, which no other reader can use, so the others open
it at its progression and KOReader gets back only XPointers (or pages).
See kodex.reading.positions.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.book import Book
from app.models.kosync import KosyncProgress
from app.models.reading_progress import ReadingProgress
from app.models.user import User
from kodex.library.models import BookFileHash
from kodex.reading import journal, positions

# KOReader reports the last page as 1.0; anything this close counts as done.
FINISHED_AT = 0.999
KODEX_DEVICE = "Kodex"
KODEX_DEVICE_ID = "kodex-web"


@dataclass
class SyncPosition:
    """One candidate position for a document, in kosync's terms."""

    progress: str | None
    percentage: float
    device: str | None
    device_id: str | None
    timestamp: dt.datetime


def books_for_document(db: Session, document: str) -> list[Book]:
    """The books whose file has this KOReader id now or had it before (the
    file changed since a device downloaded it)."""
    earlier = select(BookFileHash.book_id).where(BookFileHash.kind == "koreader", BookFileHash.value == document)
    return db.query(Book).filter(or_(Book.content_hash == document, Book.id.in_(earlier))).all()


def to_kosync_progress(book: Book, progress: ReadingProgress) -> str | None:
    """A stored position as KOSync's ``progress``, or None when it has none
    that KOReader can open (an EPUB read anywhere but in KOReader)."""
    return positions.to_koreader(book, progress.locator_kind, progress.position, progress.progress_percent)


def best_position(db: Session, user: User, document: str, *, for_koreader: bool = True) -> SyncPosition | None:
    """The newest position for this user and document: the KOSync row, or
    the position of a book here with this id.

    for_koreader leaves out positions KOReader can't open (an EPUB
    position from another reader has no XPointer); another Kodex server
    takes those too and opens them at their progression."""
    candidates: list[SyncPosition] = []
    row = _kosync_row(db, user, document)
    if row is not None and (row.progress is not None or not for_koreader):
        candidates.append(SyncPosition(row.progress, row.percentage, row.device, row.device_id, _aware(row.updated_at)))
    for book in books_for_document(db, document):
        local = journal.current(db, user.id, book.id)
        if local is None:
            continue
        progress = to_kosync_progress(book, local)
        if progress is None and for_koreader:
            continue
        candidates.append(SyncPosition(progress, local.progress_percent / 100, local.device_name or KODEX_DEVICE,
                                       local.device_id or KODEX_DEVICE_ID, _aware(local.last_read_at)))  # fmt: skip
    if not candidates:
        return None
    return max(candidates, key=lambda c: c.timestamp)


def apply_incoming(db: Session, user: User, document: str, *, progress: str | None, percentage: float,
                   device: str | None, device_id: str | None) -> None:  # fmt: skip
    """Records a position a device sent: as the KOSync row (kept for
    documents this server doesn't have, as a central sync point) and in
    the journal of every book here with this id. Commits."""
    percentage = min(max(percentage, 0.0), 1.0)
    row = _kosync_row(db, user, document) or KosyncProgress(user_id=user.id, document=document)
    row.progress = progress
    row.percentage = percentage
    row.device = device
    row.device_id = device_id
    row.updated_at = dt.datetime.now(dt.UTC)
    db.add(row)
    for book in books_for_document(db, document):
        kind, position = positions.from_koreader(book, progress, percentage)
        journal.report(db, user.id, book, journal.Report(
            position=position, locator_kind=kind, percent=round(percentage * 100, 2),
            is_finished=percentage >= FINISHED_AT, device_id=(device_id or device or "koreader")[:64],
            device_name=device[:100] if device else None))  # fmt: skip
        follow_series(db, book)
    db.commit()


def follow_series(db: Session, book: Book) -> None:
    """The first progress on a book in a series starts following that
    series (see reading_progress.save_progress)."""
    if book.series_id is not None and not book.series.is_following:
        book.series.is_following = True
        book.series.followed_at = dt.datetime.now(dt.UTC)
        db.add(book.series)


def _kosync_row(db: Session, user: User, document: str) -> KosyncProgress | None:
    return (
        db.query(KosyncProgress)
        .filter(KosyncProgress.user_id == user.id, KosyncProgress.document == document)
        .one_or_none()
    )


def _aware(value: dt.datetime | None) -> dt.datetime:
    if value is None:
        return dt.datetime.min.replace(tzinfo=dt.UTC)
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
