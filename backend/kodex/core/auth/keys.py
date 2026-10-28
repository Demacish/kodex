"""Personal API keys: ``kdx_`` and 43 random characters, shown once.
Purposes: ``app`` (a bearer token for apps), ``opds`` (the HTTP Basic
password OPDS readers send), ``kosync`` (KOReader's sync password; it
sends the MD5), ``kobo``."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from kodex.core.auth.models import ApiKey

PREFIX = "kdx_"
PURPOSES = ("app", "opds", "kosync", "kobo")


def _sha256(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create(db: Session, user: User, name: str, purpose: str) -> tuple[ApiKey, str]:
    if purpose not in PURPOSES:
        raise ValueError(f"Unknown purpose {purpose!r}")
    key = PREFIX + secrets.token_urlsafe(32)
    record = ApiKey(
        user_id=user.id,
        name=name[:100],
        purpose=purpose,
        prefix=key[:10],
        key_hash=_sha256(key),
        md5=hashlib.md5(key.encode()).hexdigest() if purpose == "kosync" else None,
    )
    db.add(record)
    db.flush()
    return record, key


def _used(db: Session, record: ApiKey) -> User | None:
    user = db.get(User, record.user_id)
    if user is None or user.disabled:
        return None
    now = dt.datetime.now(dt.UTC)
    if record.last_used_at is None or now - record.last_used_at > dt.timedelta(minutes=5):
        record.last_used_at = now
        db.commit()
    return user


def record_for_key(db: Session, key: str, purposes: tuple[str, ...]) -> ApiKey | None:
    """The key's record, if it is one of these purposes."""
    if not key.startswith(PREFIX):
        return None
    record = db.scalars(select(ApiKey).where(ApiKey.key_hash == _sha256(key))).first()
    return record if record is not None and record.purpose in purposes else None


def user_for_key(db: Session, key: str, purposes: tuple[str, ...]) -> User | None:
    """The user a key belongs to, if it is one of these purposes."""
    record = record_for_key(db, key, purposes)
    return None if record is None else _used(db, record)


def used(db: Session, record: ApiKey) -> User | None:
    """The key's user, unless disabled; notes when it was last used."""
    return _used(db, record)


def user_for_kosync(db: Session, username: str, md5: str) -> User | None:
    """KOReader sends the username and the MD5 of the password (the key)."""
    wanted = md5.lower()
    candidates = db.scalars(select(ApiKey).where(ApiKey.md5 == wanted, ApiKey.purpose == "kosync")).all()
    for record in candidates:
        user = db.get(User, record.user_id)
        if user is not None and hmac.compare_digest(user.username.casefold(), username.casefold()):
            return _used(db, record)
    return None
