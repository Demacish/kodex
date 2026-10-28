"""Secrets at rest, encrypted with a key derived from SECRET_KEY (or
SECRET_KEY_FILE): the users' authenticator secrets, and their tracker
tokens. A copy of the database alone then opens nothing.

Each use has a key of its own (``purpose``). A sealed value starts with
``sealed:``. One without it is from before SECRET_KEY was set, and reads
as it is; :func:`seal_plain` encrypts those. SECRET_KEY must not change: a
new key can't open what the old one sealed.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

PREFIX = "sealed:"


class NoSecretKey(RuntimeError):
    """SECRET_KEY isn't set, so nothing can be sealed."""


def available() -> bool:
    return bool(get_settings().secret_key)


def _fernet(purpose: str) -> Fernet:
    secret = get_settings().secret_key
    if not secret:
        raise NoSecretKey("Set SECRET_KEY to keep secrets encrypted")
    key = hashlib.sha256(f"kodex-{purpose}".encode() + b"\0" + secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal(value: str, purpose: str) -> str:
    return PREFIX + _fernet(purpose).encrypt(value.encode()).decode()


def seal_if_possible(value: str, purpose: str) -> str:
    """Sealed when SECRET_KEY is set, else as it is (a server without one keeps working)."""
    return seal(value, purpose) if available() else value


def open_(value: str, purpose: str) -> str | None:
    """The secret; None when it was sealed with another key (or there is none now)."""
    if not value.startswith(PREFIX):
        return value
    try:
        return _fernet(purpose).decrypt(value[len(PREFIX) :].encode()).decode()
    except InvalidToken, NoSecretKey:
        return None


def is_sealed(value: str | None) -> bool:
    return value is not None and value.startswith(PREFIX)
