"""Reading progress from OPDS clients, into the reading journal.

PSE clients don't report progress; the page they fetch is where they are.
But they also fetch ahead, and some download a whole book page by page to
read offline, so a page counts only when the client has been on the one
before for a while (``DWELL``): turning pages does that, prefetching and
downloading don't."""

from __future__ import annotations

import threading
import time

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.book import Book
from app.progress.sync import follow_series
from kodex.reading import journal

DWELL = 2.0  # seconds
_MAX_TRACKED = 10_000
_lock = threading.Lock()
_last_fetch: dict[tuple[int, int, str], float] = {}
_clock = time.monotonic  # replaced in tests


def device(request: Request) -> tuple[str, str]:
    """(id, name) of the reading app, from its OPDS key."""
    found = getattr(request.state, "device", None)
    return found if isinstance(found, tuple) else ("opds", "OPDS")


def _settled(user_id: int, book_id: int, device_id: str, now: float) -> bool:
    """Whether the previous page fetch was DWELL or more ago; notes this one."""
    key = (user_id, book_id, device_id)
    with _lock:
        previous = _last_fetch.get(key)
        _last_fetch[key] = now
        if len(_last_fetch) > _MAX_TRACKED:
            for stale in sorted(_last_fetch, key=_last_fetch.__getitem__)[: _MAX_TRACKED // 2]:
                del _last_fetch[stale]
    return previous is None or now - previous >= DWELL


def page_fetched(db: Session, user_id: int, book: Book, index: int, request: Request) -> None:
    """A PSE client fetched page ``index``: journals it when it reads as
    reading. Commits."""
    device_id, name = device(request)
    if not _settled(user_id, book.id, device_id, _clock()):
        return
    current = journal.current(db, user_id, book.id)
    if current is not None and current.locator_kind == "page" and current.position == str(index):
        return
    count = book.page_count or index + 1
    journal.report(db, user_id, book, journal.Report(
        position=str(index), locator_kind="page", percent=min((index + 1) / count * 100, 100.0),
        is_finished=index >= count - 1, device_id=device_id, device_name=name))  # fmt: skip
    follow_series(db, book)
    db.commit()


def forget() -> None:
    """For tests."""
    with _lock:
        _last_fetch.clear()
