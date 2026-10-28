"""Tests for app/auth.py's _decode_token: signature, time claims, issuer
and audience checks, using a locally generated RSA key instead of a real
OIDC provider.
"""

from __future__ import annotations

import time

import pytest
from fastapi import HTTPException
from joserfc import jwt
from joserfc.jwk import RSAKey

import app.auth as auth_module
from app.config import Settings

_ISSUER = "https://auth.example.com/application/o/kodex/"
_MOBILE_ISSUER = "https://auth.example.com/application/o/kodex-mobile/"


@pytest.fixture
def signing_key(monkeypatch):
    key = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
    jwks = {"keys": [key.as_dict(private=False)]}
    monkeypatch.setattr(auth_module._jwks_cache, "get", lambda issuer: jwks)
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: Settings(
            oidc_issuer=_ISSUER,
            oidc_client_id="web-client",
            oidc_mobile_issuer=_MOBILE_ISSUER,
            oidc_mobile_client_id="mobile-client",
        ),
    )
    return key


def _token(key: RSAKey, **overrides) -> str:
    now = int(time.time())
    claims = {"iss": _ISSUER, "aud": "web-client", "sub": "user-1", "iat": now, "exp": now + 300}
    claims.update(overrides)
    return jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, key)


def test_valid_token_returns_its_claims(signing_key):
    claims = auth_module._decode_token(_token(signing_key))
    assert claims["sub"] == "user-1"


def test_mobile_issuer_and_audience_are_accepted(signing_key):
    claims = auth_module._decode_token(_token(signing_key, iss=_MOBILE_ISSUER, aud=["mobile-client"]))
    assert claims["sub"] == "user-1"


def test_expired_token_is_rejected(signing_key):
    with pytest.raises(HTTPException) as excinfo:
        auth_module._decode_token(_token(signing_key, exp=int(time.time()) - 60))
    assert excinfo.value.status_code == 401


def test_unknown_issuer_is_rejected(signing_key):
    with pytest.raises(HTTPException) as excinfo:
        auth_module._decode_token(_token(signing_key, iss="https://evil.example/"))
    assert excinfo.value.detail == "Invalid token: Invalid issuer"


def test_audience_mismatch_is_rejected(signing_key):
    with pytest.raises(HTTPException) as excinfo:
        auth_module._decode_token(_token(signing_key, aud="someone-else"))
    assert excinfo.value.detail == "Invalid token: audience mismatch"


def test_token_signed_by_another_key_is_rejected(signing_key):
    other = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
    with pytest.raises(HTTPException) as excinfo:
        auth_module._decode_token(_token(other))
    assert excinfo.value.status_code == 401


def test_garbage_token_is_rejected(signing_key):
    with pytest.raises(HTTPException) as excinfo:
        auth_module._decode_token("not-a-jwt")
    assert excinfo.value.status_code == 401
