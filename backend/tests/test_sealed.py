"""Secrets at rest (kodex.core.sealed): authenticator secrets are sealed
with SECRET_KEY, old plain ones get sealed, and a changed key fails safe."""

from __future__ import annotations

import time

from sqlalchemy import select

from app.database import SessionLocal
from app.models.user import User
from kodex.core import sealed
from kodex.core.auth import factors, totp
from tests import test_auth as base

settings, client = base.settings, base.client
_csrf, _login, _make_user = base._csrf, base._login, base._make_user


def _secret_column(username: str) -> str | None:
    with SessionLocal() as db:
        return db.scalars(select(User.totp_secret).where(User.username == username)).one()


def _enable_totp(client) -> str:
    secret = client.post("/api/auth/totp", headers=_csrf(client)).json()["secret"]
    code = totp.code_at(secret, totp.step_at(time.time()))
    assert client.post("/api/auth/totp/confirm", json={"code": code}, headers=_csrf(client)).status_code == 200
    return secret


def test_an_authenticator_secret_is_kept_sealed(client, settings):
    settings(secret_key="en lång hemlig nyckel för testerna")
    _make_user("anna")
    _login(client, "anna")
    secret = _enable_totp(client)
    stored = _secret_column("anna")
    assert stored is not None and stored.startswith(sealed.PREFIX) and secret not in stored
    with SessionLocal() as db:
        user = db.scalars(select(User).where(User.username == "anna")).one()
        assert factors.check(db, user, totp.code_at(secret, totp.step_at(time.time()) + 1))


def test_plain_secrets_from_before_the_key_get_sealed(client, settings):
    _make_user("anna")
    _login(client, "anna")
    secret = _enable_totp(client)
    assert _secret_column("anna") == secret  # no SECRET_KEY yet: kept as it was
    settings(secret_key="en lång hemlig nyckel för testerna")
    with SessionLocal() as db:
        assert factors.seal_stored_secrets(db) == 1
        assert factors.seal_stored_secrets(db) == 0
    stored = _secret_column("anna")
    assert stored is not None and stored.startswith(sealed.PREFIX)
    assert sealed.open_(stored, "totp") == secret


def test_another_key_fails_safe(client, settings):
    settings(secret_key="den första nyckeln")
    _make_user("anna")
    _login(client, "anna")
    secret = _enable_totp(client)
    settings(secret_key="en annan nyckel")
    with SessionLocal() as db:
        user = db.scalars(select(User).where(User.username == "anna")).one()
        assert not factors.check(db, user, totp.code_at(secret, totp.step_at(time.time()) + 1))
