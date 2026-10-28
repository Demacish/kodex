"""Time-based one-time passwords (RFC 6238 over RFC 4226), the codes
authenticator apps show: HMAC-SHA1, six digits, 30-second steps."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import quote, urlencode

DIGITS = 6
STEP_SECONDS = 30
# Steps either side of now that are accepted, for a phone's clock that is a
# little off and for the seconds it takes to type the code.
WINDOW = 1


def new_secret() -> str:
    """160 random bits (RFC 4226's recommendation), base32 without padding."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    return base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), step.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def step_at(timestamp: float) -> int:
    return int(timestamp // STEP_SECONDS)


def verify(secret: str, code: str, *, after_step: int | None = None, now: float | None = None) -> int | None:
    """The step ``code`` belongs to, or None. A step at or before
    ``after_step`` (the last one used) is refused, so a code works once."""
    code = "".join(code.split())
    if len(code) != DIGITS or not code.isdigit():
        return None
    current = step_at(time.time() if now is None else now)
    for step in range(current - WINDOW, current + WINDOW + 1):
        if after_step is not None and step <= after_step:
            continue
        if hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def uri(secret: str, account: str, issuer: str = "Kodex") -> str:
    """The otpauth:// link a QR code carries (Google Authenticator's key URI
    format, which every app reads)."""
    label = quote(f"{issuer}:{account}", safe=":@")
    query = urlencode({"secret": secret, "issuer": issuer, "digits": DIGITS, "period": STEP_SECONDS})
    return f"otpauth://totp/{label}?{query}"
