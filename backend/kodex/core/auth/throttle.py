"""Slows down password guessing: once a username, or an address, has too
many failed logins within ``login_lockout_minutes``, it waits until the
oldest of them is that old. A success clears the username's failures."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import delete, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.config import get_settings
from kodex.core.auth.models import LoginFailure


def _wait(db: Session, column: InstrumentedAttribute[str] | InstrumentedAttribute[str | None], value: str, limit: int,
          window: dt.timedelta, now: dt.datetime) -> int:  # fmt: skip
    since = now - window
    count, oldest = db.execute(
        select(func.count(), func.min(LoginFailure.at)).where(column == value, LoginFailure.at > since)
    ).one()
    if count < limit or oldest is None:
        return 0
    return max(1, int((oldest + window - now).total_seconds()) + 1)


def seconds_to_wait(db: Session, username: str, ip: str | None) -> int:
    settings = get_settings()
    window = dt.timedelta(minutes=settings.login_lockout_minutes)
    now = dt.datetime.now(dt.UTC)
    waits = [_wait(db, LoginFailure.username, username.casefold(), settings.login_max_failures, window, now)]
    if ip:
        waits.append(_wait(db, LoginFailure.ip, ip, settings.login_max_failures_per_ip, window, now))
    return max(waits)


def record_failure(db: Session, username: str, ip: str | None) -> None:
    db.add(LoginFailure(username=username.casefold()[:255], ip=ip))
    db.commit()


def clear(db: Session, username: str) -> None:
    db.execute(delete(LoginFailure).where(LoginFailure.username == username.casefold()))


def remove_old(db: Session, now: dt.datetime) -> int:
    result = db.execute(delete(LoginFailure).where(LoginFailure.at < now - dt.timedelta(days=1)))
    return int(getattr(result, "rowcount", 0) or 0)
