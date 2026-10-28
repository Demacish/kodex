"""OpenID Connect login (Authorization Code with PKCE), with httpx and
joserfc: discovery, the redirect to the provider, and on the way back the
code exchange and a verified ID token (signature, issuer, audience, expiry,
nonce). The state, nonce and PKCE verifier wait in ``oidc_logins`` for
ten minutes and are used once."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar, cast
from urllib.parse import quote_plus, urlencode

import httpx
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from kodex.core.auth.models import OidcLogin

T = TypeVar("T")
LOGIN_LIFETIME = dt.timedelta(minutes=10)
_CACHE_SECONDS = 3600
_SIGNING_ALGORITHMS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA")


class OidcError(Exception):
    """The login can't go on; the message says why (shown to the user)."""


@dataclass(frozen=True)
class Provider:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str | None
    algorithms: tuple[str, ...]


def enabled() -> bool:
    settings = get_settings()
    return bool(settings.oidc_issuer and settings.oidc_client_id)


def http_client() -> httpx.Client:
    """Replaced in tests with one on an httpx.MockTransport."""
    return httpx.Client(timeout=10, follow_redirects=False)


class _Cache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, tuple[float, object]] = {}

    def get(self, key: str, fetch: Callable[[], T], *, refresh: bool = False) -> T:
        with self._lock:
            hit = self._values.get(key)
            if hit is not None and not refresh and time.monotonic() - hit[0] < _CACHE_SECONDS:
                return cast(T, hit[1])
            value = fetch()
            self._values[key] = (time.monotonic(), value)
            return value

    def clear(self) -> None:
        with self._lock:
            self._values.clear()


_cache = _Cache()


def _get_json(url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        with http_client() as client:
            response = client.get(url, **kwargs)
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OidcError(f"The identity provider didn't answer: {exc}") from exc
    if not isinstance(body, dict):
        raise OidcError("The identity provider answered with something else than an object")
    return body


def provider() -> Provider:
    issuer = get_settings().oidc_issuer

    def fetch() -> Provider:
        doc = _get_json(f"{issuer.rstrip('/')}/.well-known/openid-configuration")
        try:
            offered = doc.get("id_token_signing_alg_values_supported") or ["RS256"]
            return Provider(doc["issuer"], doc["authorization_endpoint"], doc["token_endpoint"], doc["jwks_uri"],
                            doc.get("userinfo_endpoint"), tuple(a for a in offered if a in _SIGNING_ALGORITHMS))  # fmt: skip
        except KeyError as exc:
            raise OidcError(f"The provider's discovery document lacks {exc}") from exc

    return _cache.get(f"discovery:{issuer}", fetch)


def _keys(jwks_uri: str, *, refresh: bool = False) -> KeySet:
    return _cache.get(f"jwks:{jwks_uri}", lambda: KeySet.import_key_set(_get_json(jwks_uri)), refresh=refresh)  # type: ignore[arg-type]


def _challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def begin(db: Session, redirect_uri: str, next_path: str, *, link_user_id: int | None = None) -> str:
    """Starts a login, or with ``link_user_id`` the linking of that account;
    returns the provider URL to send the browser to."""
    settings, found = get_settings(), provider()
    login = OidcLogin(state=secrets.token_urlsafe(32), nonce=secrets.token_urlsafe(32),
                      code_verifier=secrets.token_urlsafe(64), next_path=next_path, link_user_id=link_user_id)  # fmt: skip
    db.add(login)
    db.commit()
    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": redirect_uri,
        "scope": settings.oidc_scopes,
        "state": login.state,
        "nonce": login.nonce,
        "code_challenge": _challenge(login.code_verifier),
        "code_challenge_method": "S256",
    }
    separator = "&" if "?" in found.authorization_endpoint else "?"
    return found.authorization_endpoint + separator + urlencode(params)


def _verify_id_token(token: str, found: Provider, client_id: str, nonce: str) -> dict[str, Any]:
    algorithms = list(found.algorithms or ("RS256",))
    try:
        try:
            decoded = jwt.decode(token, _keys(found.jwks_uri), algorithms=algorithms)
        except JoseError:  # a rotated key: fetch the set again, once
            decoded = jwt.decode(token, _keys(found.jwks_uri, refresh=True), algorithms=algorithms)
        jwt.JWTClaimsRegistry(leeway=60, iss={"essential": True, "value": found.issuer},
                              aud={"essential": True, "value": client_id}, sub={"essential": True},
                              nonce={"essential": True, "value": nonce}).validate(decoded.claims)  # fmt: skip
    except (JoseError, ValueError) as exc:
        raise OidcError(f"The ID token is not valid: {exc}") from exc
    return dict(decoded.claims)


def finish(db: Session, state: str, code: str, redirect_uri: str) -> tuple[dict[str, Any], str, int | None]:
    """Completes a login: the verified claims (with userinfo's added where
    the ID token lacks them), the path the user was going to, and the
    account being linked, if that is what this was."""
    settings = get_settings()
    login = db.get(OidcLogin, state)
    if login is None:
        raise OidcError("Unknown or used login; start again")
    db.delete(login)
    db.commit()
    if dt.datetime.now(dt.UTC) - login.created_at > LOGIN_LIFETIME:
        raise OidcError("The login took too long; start again")
    found = provider()
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": settings.oidc_client_id, "code_verifier": login.code_verifier}  # fmt: skip
    headers = {}
    if settings.oidc_client_secret:  # client_secret_basic: each part form-encoded first (RFC 6749, 2.3.1)
        pair = f"{quote_plus(settings.oidc_client_id)}:{quote_plus(settings.oidc_client_secret)}"
        headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
    try:
        with http_client() as client:
            response = client.post(found.token_endpoint, data=form, headers=headers)
        tokens = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OidcError(f"The identity provider didn't answer: {exc}") from exc
    if response.status_code != 200 or "id_token" not in tokens:
        raise OidcError(f"The identity provider refused the login: {tokens.get('error', response.status_code)}")
    claims = _verify_id_token(tokens["id_token"], found, settings.oidc_client_id, login.nonce)
    if found.userinfo_endpoint and tokens.get("access_token"):
        info = _get_json(found.userinfo_endpoint, headers={"Authorization": f"Bearer {tokens['access_token']}"})
        if info.get("sub") == claims["sub"]:
            claims = {**info, **claims}
    return claims, login.next_path, login.link_user_id


def remove_stale(db: Session, now: dt.datetime) -> int:
    result = db.execute(delete(OidcLogin).where(OidcLogin.created_at < now - LOGIN_LIFETIME))
    return int(getattr(result, "rowcount", 0) or 0)
