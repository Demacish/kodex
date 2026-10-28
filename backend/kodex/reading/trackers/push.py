"""Sending what was read to the trackers.

A linked series' progress is the highest whole number among its finished
books (volume 7 read means seven volumes read, also when one before it was
skipped), or the number of finished books when they have no numbers. It
goes to the service only when it is more than both what Kodex sent last
and what the service already has, so reading elsewhere, or a book marked
unread here, never moves the service backwards.
"""

from __future__ import annotations

import datetime as dt
import logging
from math import floor

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.book import Book
from app.models.reading_progress import ReadingProgress
from kodex.reading.trackers import secrets
from kodex.reading.trackers.models import TrackerAccount, TrackerLink
from kodex.reading.trackers.services import Expired, Service, Tokens, TrackerError, Unit, service

logger = logging.getLogger(__name__)


def progress(db: Session, user_id: int, series_id: int) -> int:
    finished = db.scalars(
        select(Book.number)
        .join(ReadingProgress, ReadingProgress.book_id == Book.id)
        .where(
            Book.series_id == series_id,
            Book.missing_since.is_(None),
            ReadingProgress.user_id == user_id,
            ReadingProgress.is_finished.is_(True),
        )  # fmt: skip
    ).all()
    numbers = [floor(n) for n in finished if n is not None and n >= 0]
    return max(numbers) if numbers else len(finished)


def tokens_of(db: Session, account: TrackerAccount, impl: Service) -> Tokens:
    """The account's tokens, refreshed first when they are about to expire."""
    access = secrets.open_(account.access_token)
    if access is None:
        raise Expired("The account was connected under another SECRET_KEY; connect it again")
    refresh = secrets.open_(account.refresh_token) if account.refresh_token else None
    tokens = Tokens(access, refresh, account.expires_at)
    soon = dt.datetime.now(dt.UTC) + dt.timedelta(days=1)
    if tokens.expires_at is not None and tokens.expires_at < soon and tokens.refresh:
        renewed = impl.refresh(tokens)
        if renewed is not None:
            store(account, renewed)
            db.commit()
            return renewed
    return tokens


def store(account: TrackerAccount, tokens: Tokens) -> None:
    account.access_token = secrets.seal(tokens.access)
    account.refresh_token = secrets.seal(tokens.refresh) if tokens.refresh else None
    account.expires_at = tokens.expires_at


def push(db: Session, link: TrackerLink, impl: Service | None = None, *, force: bool = False) -> bool:
    """Sends the link's progress when it moved; True when something was sent. Errors are kept on the link."""
    impl = impl or service(link.service)
    account = db.scalars(
        select(TrackerAccount).where(TrackerAccount.user_id == link.user_id, TrackerAccount.service == link.service)
    ).first()
    if impl is None or account is None:
        return False
    read = progress(db, link.user_id, link.series_id)
    if read <= link.sent_progress and not force:
        return False
    unit: Unit = "volume" if link.unit == "volume" else "chapter"
    try:
        tokens = tokens_of(db, account, impl)
        current = impl.entry(tokens, account.remote_user_id, link.remote_id)
        listed = current is not None and current.listed
        there = current.progress(unit) if current is not None and listed else 0
        if read <= there and listed:
            link.sent_progress = max(link.sent_progress, read)
            link.error = None
            db.commit()
            return False
        total = current.total(unit) if current else None
        impl.save(
            tokens, account.remote_user_id, link.remote_id, unit, read, completed=total is not None and read >= total
        )
    except TrackerError as exc:
        link.error = str(exc)[:500]
        db.commit()
        logger.info("tracker %s for series %s: %s", link.service, link.series_id, exc)
        return False
    link.sent_progress = read
    link.sent_at = dt.datetime.now(dt.UTC)
    link.error = None
    db.commit()
    return True


def push_all(db: Session) -> int:
    """Every link whose series moved since it was sent; how many were sent."""
    sent = 0
    for link in db.scalars(select(TrackerLink).order_by(TrackerLink.id)).all():
        if push(db, link):
            sent += 1
    return sent
