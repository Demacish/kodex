"""Tracker tokens at rest (kodex.core.sealed, with their own key)."""

from __future__ import annotations

from kodex.core import sealed
from kodex.core.sealed import NoSecretKey

__all__ = ["NoSecretKey", "available", "open_", "seal"]

_PURPOSE = "trackers"


def available() -> bool:
    return sealed.available()


def seal(value: str) -> str:
    return sealed.seal(value, _PURPOSE)


def open_(value: str) -> str | None:
    """The token, or None when it was sealed under another SECRET_KEY."""
    if not sealed.is_sealed(value):
        return None  # tokens are always sealed; anything else isn't one of ours
    return sealed.open_(value, _PURPOSE)
