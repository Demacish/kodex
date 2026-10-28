"""Web sessions: a random token in an HttpOnly cookie, stored hashed, with
a CSRF token the client echoes in ``X-CSRF-Token`` on unsafe requests
(double submit: the token is also in a readable cookie, which another site
can't read). Sessions last ``session_days`` and are extended while used."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.user import User
from kodex.core.auth.models import UserSession

SESSION_COOKIE = "kodex_session"
CSRF_COOKIE = "kodex_csrf"
CSRF_HEADER = "x-csrf-token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_TOUCH_EVERY = dt.timedelta(minutes=5)
# A session not remembered on its device lasts this long after its last use.
FORGET_AFTER = dt.timedelta(days=1)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _secure(request: Request) -> bool:
    setting = get_settings().cookie_secure.lower()
    if setting in ("true", "false"):
        return setting == "true"
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.split(",")[0].strip() == "https"


def _lifetime(remember: bool) -> dt.timedelta:
    return dt.timedelta(days=get_settings().session_days) if remember else FORGET_AFTER


def start(db: Session, user: User, request: Request, response: Response, *, remember: bool = True) -> UserSession:
    """Logs ``user`` in: a new session, its cookies set on ``response``.
    Without ``remember``, the cookies go when the browser closes."""
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    now = dt.datetime.now(dt.UTC)
    session = UserSession(user_id=user.id, token_hash=_hash(token), csrf_token=csrf,
                          user_agent=(request.headers.get("user-agent") or "")[:255] or None,
                          expires_at=now + _lifetime(remember), last_seen_at=now, remember=remember)  # fmt: skip
    db.add(session)
    user.last_login_at = now
    db.flush()
    secure = _secure(request)
    max_age = get_settings().session_days * 86400 if remember else None
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, samesite="lax", secure=secure, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, samesite="lax", secure=secure, path="/")
    return session


def forget(db: Session, request: Request) -> None:
    """Ends the request's session, if any (before a new login replaces it)."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.execute(delete(UserSession).where(UserSession.token_hash == _hash(token)))


def end(db: Session, request: Request, response: Response) -> None:
    forget(db, request)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def current(db: Session, request: Request) -> tuple[UserSession, User] | None:
    """The request's session and user, or None without a valid one. An
    unsafe request without the matching CSRF token is refused."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = db.scalars(select(UserSession).where(UserSession.token_hash == _hash(token))).first()
    now = dt.datetime.now(dt.UTC)
    if session is None or session.expires_at <= now:
        return None
    user = db.get(User, session.user_id)
    if user is None or user.disabled:
        return None
    if request.method not in _SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not hmac.compare_digest(sent, session.csrf_token):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token missing or wrong")
    if now - session.last_seen_at > _TOUCH_EVERY:
        session.last_seen_at = now
        session.expires_at = max(session.expires_at, now + _lifetime(session.remember))
        db.commit()
    return session, user


def end_all(db: Session, user_id: int, *, except_id: int | None = None) -> None:
    """Logs a user out everywhere (after a password change, say)."""
    query = delete(UserSession).where(UserSession.user_id == user_id)
    if except_id is not None:
        query = query.where(UserSession.id != except_id)
    db.execute(query)


def remove_expired(db: Session, now: dt.datetime) -> int:
    result = db.execute(delete(UserSession).where(UserSession.expires_at < now))
    return int(getattr(result, "rowcount", 0) or 0)
