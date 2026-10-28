"""One-time sign-in links: an admin makes one for a user, who opens it and
sets a password. They welcome new users, and v1's users who only ever
logged in through Authentik, without mail and without the admin knowing
the password."""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.user import User
from kodex.core.auth.models import SignInLink

LIFETIME = dt.timedelta(days=3)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create(db: Session, user: User) -> tuple[str, dt.datetime]:
    """A new link token for ``user`` (any older link stops working)."""
    db.execute(delete(SignInLink).where(SignInLink.user_id == user.id))
    token = secrets.token_urlsafe(32)
    expires = dt.datetime.now(dt.UTC) + LIFETIME
    db.add(SignInLink(user_id=user.id, token_hash=_hash(token), expires_at=expires))
    db.flush()
    return token, expires


def user_for(db: Session, token: str) -> User | None:
    link = db.scalars(select(SignInLink).where(SignInLink.token_hash == _hash(token))).first()
    if link is None or link.expires_at <= dt.datetime.now(dt.UTC):
        return None
    user = db.get(User, link.user_id)
    return None if user is None or user.disabled else user


def use(db: Session, token: str) -> User | None:
    """The link's user, with the link removed so it works once."""
    query = delete(SignInLink).where(SignInLink.token_hash == _hash(token)).returning(SignInLink.user_id,
                                                                                       SignInLink.expires_at)  # fmt: skip
    found = db.execute(query).first()
    if found is None or found.expires_at <= dt.datetime.now(dt.UTC):
        return None
    user = db.get(User, found.user_id)
    return None if user is None or user.disabled else user


def remove_expired(db: Session, now: dt.datetime) -> int:
    result = db.execute(delete(SignInLink).where(SignInLink.expires_at < now))
    return int(getattr(result, "rowcount", 0) or 0)
