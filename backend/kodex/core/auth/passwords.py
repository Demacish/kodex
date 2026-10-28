"""argon2id password hashing (argon2-cffi's defaults, RFC 9106's second
recommendation), with rehashing when the parameters change."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 8
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored: str | None, password: str) -> bool:
    if not stored:
        _hasher.hash(password)  # same work as a real check, so timing says nothing
        return False
    try:
        return _hasher.verify(stored, password)
    except VerifyMismatchError, VerificationError, InvalidHashError:
        return False


def needs_rehash(stored: str) -> bool:
    return _hasher.check_needs_rehash(stored)


def check_strength(password: str) -> str | None:
    """Why the password won't do, or None."""
    if len(password) < MIN_LENGTH:
        return f"at least {MIN_LENGTH} characters"
    return None
