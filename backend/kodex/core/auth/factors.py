"""Two-step login: an authenticator app (TOTP, kodex.core.auth.totp), with
one-time recovery codes for when the app is gone, and the tickets that
carry an unfinished login or passkey ceremony from one request to the next
(``auth_challenges``, a few minutes each)."""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import secrets
from collections.abc import Collection

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.user import User
from kodex.core import sealed
from kodex.core.auth import totp
from kodex.core.auth.models import AuthChallenge, RecoveryCode

logger = logging.getLogger(__name__)

TICKET_LIFETIME = dt.timedelta(minutes=5)
# Codes one ticket may try before the password has to be given again; the
# failures count towards the username's login limit too (throttle).
MAX_ATTEMPTS = 5
RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i


def enabled(user: User) -> bool:
    return user.totp_enabled_at is not None and user.totp_secret is not None


def new_ticket(db: Session, purpose: str, user_id: int | None = None, challenge: bytes | None = None) -> AuthChallenge:
    now = dt.datetime.now(dt.UTC)
    db.execute(delete(AuthChallenge).where(AuthChallenge.created_at < now - TICKET_LIFETIME))
    row = AuthChallenge(ticket=secrets.token_urlsafe(32), purpose=purpose, user_id=user_id, challenge=challenge,
                        created_at=now)  # fmt: skip
    db.add(row)
    db.flush()
    return row


def _fresh(row: AuthChallenge | None, purposes: Collection[str]) -> AuthChallenge | None:
    if row is None or row.purpose not in purposes:
        return None
    if dt.datetime.now(dt.UTC) - row.created_at > TICKET_LIFETIME:
        return None
    return row


def ticket(db: Session, value: str, purposes: Collection[str]) -> AuthChallenge | None:
    """A ticket that is still valid, locked until the transaction ends."""
    query = select(AuthChallenge).where(AuthChallenge.ticket == value).with_for_update()
    return _fresh(db.scalars(query).first(), purposes)


def take(db: Session, value: str, purposes: Collection[str]) -> AuthChallenge | None:
    """Removes a ticket and returns it if it was valid: it works once."""
    query = delete(AuthChallenge).where(AuthChallenge.ticket == value).returning(AuthChallenge)
    return _fresh(db.scalars(query).first(), purposes)


_PURPOSE = "totp"


def _secret(user: User) -> str | None:
    """The authenticator secret in the clear (it is kept sealed when SECRET_KEY is set)."""
    if user.totp_secret is None:
        return None
    found = sealed.open_(user.totp_secret, _PURPOSE)
    if found is None:
        logger.warning("User %s's authenticator secret was sealed under another SECRET_KEY", user.id)
    return found


def start_totp(user: User) -> str:
    """A new secret, waiting for its first code (confirm_totp)."""
    secret = totp.new_secret()
    user.totp_secret = sealed.seal_if_possible(secret, _PURPOSE)
    user.totp_enabled_at = None
    user.totp_last_step = None
    return secret


def seal_stored_secrets(db: Session) -> int:
    """Seals the authenticator secrets kept from before SECRET_KEY was set; how many."""
    if not sealed.available():
        return 0
    users = db.scalars(
        select(User).where(User.totp_secret.is_not(None), User.totp_secret.not_like(f"{sealed.PREFIX}%"))
    ).all()
    for user in users:
        user.totp_secret = sealed.seal(user.totp_secret or "", _PURPOSE)
    db.commit()
    return len(users)


def confirm_totp(db: Session, user: User, code: str) -> list[str] | None:
    """Turns two-step login on once the app shows the right code; returns
    the new recovery codes, or None for a wrong code."""
    secret = _secret(user)
    if secret is None or user.totp_enabled_at is not None:
        return None
    step = totp.verify(secret, code)
    if step is None:
        return None
    user.totp_enabled_at = dt.datetime.now(dt.UTC)
    user.totp_last_step = step
    return new_recovery_codes(db, user)


def disable(db: Session, user: User) -> None:
    user.totp_secret = None
    user.totp_enabled_at = None
    user.totp_last_step = None
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))


def _normalize(code: str) -> str:
    return "".join(c for c in code.lower() if c.isalnum())


def _hash(code: str) -> str:
    return hashlib.sha256(_normalize(code).encode()).hexdigest()


def new_recovery_codes(db: Session, user: User) -> list[str]:
    """Replaces the user's recovery codes; they are shown this once."""
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
        db.add(RecoveryCode(user_id=user.id, code_hash=_hash(raw)))
    db.flush()
    return codes


def recovery_codes_left(db: Session, user_id: int) -> int:
    query = select(func.count()).where(RecoveryCode.user_id == user_id, RecoveryCode.used_at.is_(None))
    return int(db.scalar(query) or 0)


def check(db: Session, user: User, code: str) -> bool:
    """Whether ``code`` is the authenticator app's current code or an unused
    recovery code; either is used up by this. The user row is locked so
    two requests can't use the same code."""
    db.refresh(user, with_for_update=True)
    secret = _secret(user)
    if not enabled(user) or secret is None:
        return False
    normalized = _normalize(code)
    if normalized.isdigit():
        step = totp.verify(secret, normalized, after_step=user.totp_last_step)
        if step is None:
            return False
        user.totp_last_step = step
        return True
    found = db.scalars(select(RecoveryCode).where(RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None),
                                                  RecoveryCode.code_hash == _hash(normalized))).first()  # fmt: skip
    if found is None:
        return False
    found.used_at = dt.datetime.now(dt.UTC)
    return True


def remove_stale(db: Session, now: dt.datetime) -> int:
    result = db.execute(delete(AuthChallenge).where(AuthChallenge.created_at < now - TICKET_LIFETIME))
    return int(getattr(result, "rowcount", 0) or 0)
