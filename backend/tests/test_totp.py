"""kodex.core.auth.totp against RFC 6238's test vectors (SHA-1; the RFC's
codes have eight digits, an app's six are their last six)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from kodex.core.auth import totp

# RFC 6238 appendix B: the ASCII secret "12345678901234567890", in base32.
_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


@pytest.mark.parametrize(
    ("timestamp", "rfc_code"),
    [(59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"), (1234567890, "89005924"),
     (2000000000, "69279037"), (20000000000, "65353130")],
)  # fmt: skip
def test_rfc_6238_vectors(timestamp, rfc_code):
    assert totp.code_at(_SECRET, totp.step_at(timestamp)) == rfc_code[-6:]


def test_a_code_is_accepted_a_step_either_side_and_only_once():
    now = 1234567890.0
    step = totp.step_at(now)
    for neighbour in (step - 1, step, step + 1):
        assert totp.verify(_SECRET, totp.code_at(_SECRET, neighbour), now=now) == neighbour
    assert totp.verify(_SECRET, totp.code_at(_SECRET, step - 2), now=now) is None
    assert totp.verify(_SECRET, totp.code_at(_SECRET, step), after_step=step, now=now) is None
    assert totp.verify(_SECRET, totp.code_at(_SECRET, step + 1), after_step=step, now=now) == step + 1


@pytest.mark.parametrize("code", ["", "12345", "1234567", "abcdef", "12 34 5x"])
def test_malformed_codes_are_refused(code):
    assert totp.verify(_SECRET, code, now=59) is None


def test_spaces_in_a_code_are_ignored():
    code = totp.code_at(_SECRET, totp.step_at(59))
    assert totp.verify(_SECRET, f"{code[:3]} {code[3:]}", now=59) == totp.step_at(59)


def test_new_secrets_are_random_base32_and_work():
    first, second = totp.new_secret(), totp.new_secret()
    assert first != second and len(first) == 32
    assert totp.verify(first, totp.code_at(first, 1000), now=1000 * 30) == 1000


def test_the_key_uri():
    uri = totp.uri(_SECRET, "anna lind")
    parts = urlsplit(uri)
    assert (parts.scheme, parts.netloc, parts.path) == ("otpauth", "totp", "/Kodex:anna%20lind")
    query = parse_qs(parts.query)
    assert query["secret"] == [_SECRET] and query["issuer"] == ["Kodex"] and query["digits"] == ["6"]
