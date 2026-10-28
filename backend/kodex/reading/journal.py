"""Recording positions in the reading journal and deriving the current
state from it. The newest report the server received wins (client clocks
can't be trusted), except that a device's report with a lower counter
than one already recorded is late, and is kept in the journal without
moving the position back. Every source reports the same way: the web
reader, v1's clients, KOReader (KOSync), Kobo and OPDS clients.

Old entries are compacted (``compact``): past ``READING_JOURNAL_DAYS``, a
book keeps its last entry of each day, and every finish and restart."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.book import Book
from app.models.reading_progress import ReadingProgress
from kodex.reading import positions
from kodex.reading.models import ReadingEvent

SERVER_DEVICE = "kodex"


@dataclass(frozen=True)
class Report:
    """One position a device reports."""

    position: str | None
    percent: float
    is_finished: bool
    locator_kind: str | None = None
    chapter: str | None = None
    device_id: str | None = None
    device_name: str | None = None
    client_seq: int | None = None
    client_at: dt.datetime | None = None


def kind_of(*, is_finished: bool, restarted: bool) -> str:
    if is_finished:
        return "finished"
    return "reset" if restarted else "progress"


def current(db: Session, user_id: int, book_id: int) -> ReadingProgress | None:
    query = select(ReadingProgress).where(ReadingProgress.user_id == user_id, ReadingProgress.book_id == book_id)
    return db.scalars(query).first()


def record(db: Session, progress: ReadingProgress, *, device_id: str | None, device_name: str | None,
           client_seq: int | None, client_at: dt.datetime | None, position: str | None, percent: float,
           is_finished: bool, chapter: str | None, locator_kind: str | None = None) -> bool:  # fmt: skip
    """Adds a report to the journal; True when it is the newest and should
    become the book's position, False for a late or repeated one."""
    device = device_id or SERVER_DEVICE
    newest = True
    if client_seq is not None:
        latest = db.scalar(
            select(func.max(ReadingEvent.client_seq)).where(
                ReadingEvent.user_id == progress.user_id,
                ReadingEvent.book_id == progress.book_id,
                ReadingEvent.device_id == device,
            )
        )
        if latest is not None and client_seq <= latest:
            if client_seq == latest:
                return False  # the same report again (a retry): nothing new
            newest = False
    restarted = bool(progress.is_finished) and not is_finished and newest
    db.add(ReadingEvent(user_id=progress.user_id, book_id=progress.book_id, device_id=device,
                        device_name=device_name, client_seq=client_seq, client_at=client_at,
                        kind=kind_of(is_finished=is_finished, restarted=restarted), position=position,
                        locator_kind=locator_kind, progress_percent=percent, chapter=chapter))  # fmt: skip
    return newest


def report(db: Session, user_id: int, book: Book, sent: Report) -> tuple[ReadingProgress, bool]:
    """Journals a report and, when it is the newest, makes it the book's
    position. Returns the position row and whether it moved. Doesn't
    commit."""
    progress = current(db, user_id, book.id)
    if progress is None:
        progress = ReadingProgress(user_id=user_id, book_id=book.id, progress_percent=0.0, is_finished=False)
        db.add(progress)
        db.flush()
    kind, position = positions.normalize(book, sent.locator_kind, sent.position)
    percent = min(max(sent.percent, 0.0), 100.0)
    moved = record(db, progress, device_id=sent.device_id, device_name=sent.device_name, client_seq=sent.client_seq,
                   client_at=sent.client_at, position=position, percent=percent, is_finished=sent.is_finished,
                   chapter=sent.chapter, locator_kind=kind)  # fmt: skip
    if moved:
        progress.position = position
        progress.locator_kind = kind
        progress.progress_percent = percent
        progress.is_finished = sent.is_finished
        progress.chapter = sent.chapter
        progress.device_id = sent.device_id or SERVER_DEVICE
        progress.device_name = sent.device_name
        progress.dismissed_at = None
        progress.last_read_at = dt.datetime.now(dt.UTC)
    return progress, moved


def entries(db: Session, user_id: int, book_id: int, limit: int = 50) -> list[ReadingEvent]:
    query = (
        select(ReadingEvent)
        .where(ReadingEvent.user_id == user_id, ReadingEvent.book_id == book_id)
        .order_by(ReadingEvent.received_at.desc(), ReadingEvent.id.desc())
        .limit(limit)
    )
    return list(db.scalars(query))


def compact(db: Session, before: dt.datetime) -> int:
    """Thins out entries received before ``before`` to the last one per
    user, book and day (UTC), keeping every finish and restart; returns
    how many went."""
    result = db.execute(
        text(
            "DELETE FROM reading_events WHERE id IN ("
            " SELECT id FROM ("
            "  SELECT id, kind, row_number() OVER ("
            "   PARTITION BY user_id, book_id, date_trunc('day', received_at AT TIME ZONE 'UTC')"
            "   ORDER BY received_at DESC, id DESC) AS newest"
            "  FROM reading_events WHERE received_at < :before) AS ranked"
            " WHERE newest > 1 AND kind = 'progress')"
        ),
        {"before": before},
    )
    return int(getattr(result, "rowcount", 0) or 0)
