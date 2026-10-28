"""Setting up a server's first admin (POST /api/auth/setup).

A server without users takes whoever comes first: that is a fresh install,
and its owner is the one opening it. A server with users but no admin who
can log in is another matter: its accounts came from v1, which logged in
only through Authentik, or the identity provider they used is no longer
set up. Its libraries and reading are already there, so the same form also
wants a setup code that the api writes to its log when it starts. Only
whoever runs the server can read that, not whoever finds its address first.

The code lives in the api process (Kodex runs one); a restart writes a new
one. It works once, and once an admin can log in there is none.
"""

from __future__ import annotations

import hmac
import logging
import secrets
from typing import Literal

from sqlalchemy import ColumnElement, exists, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.user import User
from kodex.core.auth import oidc
from kodex.core.auth.models import Passkey

logger = logging.getLogger(__name__)

State = Literal["ready", "fresh", "claim"]
# Easy to read out of a log and type: no 0/O or 1/I.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
# The key failed codes are counted under (kodex.core.auth.throttle).
THROTTLE_KEY = "(setup code)"

_code: str | None = None


def state(db: Session) -> State:
    """``fresh`` without users, ``claim`` when no admin can log in, else ``ready``."""
    settings = get_settings()
    if settings.auth_disabled:
        return "ready"
    if db.scalars(select(User.id).limit(1)).first() is None:
        return "fresh"
    if oidc.enabled() or not settings.local_login_enabled:
        return "ready"  # the provider decides who is an admin, or there is no form to claim with
    can_log_in: list[ColumnElement[bool]] = [User.password_hash.isnot(None)]
    if settings.passkeys_enabled:
        can_log_in.append(exists().where(Passkey.user_id == User.id))
    admin = select(User.id).where(User.role == "admin", User.disabled.is_(False), or_(*can_log_in))
    return "ready" if db.scalars(admin.limit(1)).first() is not None else "claim"


def _new_code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def announce(db: Session) -> str | None:
    """At start: when no admin can log in, a new setup code, in the log."""
    global _code
    if state(db) != "claim":
        _code = None
        return None
    _code = _new_code()
    address = get_settings().public_app_url.rstrip("/") or "the server's address"
    logger.warning(
        "No admin can log in to this server yet. Open %s in a browser and enter the setup code %s, "
        "with the admin's username and a new password. (An account that already exists keeps its "
        "libraries, collections and reading.)",
        address,
        _code,
    )
    return _code


def check_code(given: str) -> bool:
    if _code is None:
        return False
    typed = given.strip().upper().replace(" ", "").replace("-", "")
    return hmac.compare_digest(typed.encode(), _code.replace("-", "").encode())


def forget_code() -> None:
    global _code
    _code = None
