"""Tests for app/auth.py's require_admin_or_upload_key — the B7 upload
endpoint's alternate auth path for a headless folder-watcher script (see
app/config.py's upload_api_key docstring). Called directly as a plain
Python function rather than through a TestClient/HTTP round trip:
dependency_overrides (the api fixture's usual admin bypass, see
conftest.py) can't reach into this function's own get_current_user/
require_admin calls, since those are made as plain function calls, not
their own Depends() — see require_admin_or_upload_key's own docstring
for why. Route-level "does the endpoint propagate a 403" behavior is
covered separately in test_library_upload.py.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import sessionmaker

from app.auth import require_admin_or_upload_key
from app.config import Settings
from app.models.user import User
from tests.db import fresh_engine


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""})


@pytest.fixture
def db():
    engine = fresh_engine()
    return sessionmaker(bind=engine, future=True)()


def test_valid_upload_key_succeeds_without_any_credentials(db, monkeypatch):
    monkeypatch.setattr(
        "app.auth.get_settings", lambda: Settings(upload_api_key="secret", oidc_issuer="https://idp.test/")
    )

    # No exception — succeeds purely on the header, no bearer token needed.
    require_admin_or_upload_key(_request(), x_kodex_upload_key="secret", credentials=None, db=db)


def test_wrong_upload_key_falls_back_and_fails_without_credentials(db, monkeypatch):
    monkeypatch.setattr(
        "app.auth.get_settings", lambda: Settings(upload_api_key="secret", oidc_issuer="https://idp.test/")
    )

    with pytest.raises(HTTPException) as exc_info:
        require_admin_or_upload_key(_request(), x_kodex_upload_key="wrong", credentials=None, db=db)
    assert exc_info.value.status_code == 401


def test_no_upload_key_configured_falls_back_to_admin_check(db, monkeypatch):
    monkeypatch.setattr("app.auth.get_settings", lambda: Settings(upload_api_key=""))

    with pytest.raises(HTTPException) as exc_info:
        require_admin_or_upload_key(_request(), x_kodex_upload_key=None, credentials=None, db=db)
    assert exc_info.value.status_code == 401  # missing bearer token, not a 403


def test_no_upload_key_but_valid_admin_bearer_token_succeeds(db, monkeypatch):
    monkeypatch.setattr("app.auth.get_settings", lambda: Settings(auth_disabled=True))
    # AUTH_DISABLED short-circuits get_current_user to a fixed dev user
    # (is_admin=True) — the simplest way to exercise the real fallback
    # path succeeding without needing a real signed JWT.
    require_admin_or_upload_key(_request(), x_kodex_upload_key=None, credentials=None, db=db)


def _with_groups() -> Settings:
    return Settings(upload_api_key="secret", oidc_issuer="https://idp.test/", oidc_required_group="kodex-users",
                    oidc_admin_group="kodex-admins")  # fmt: skip


def test_wrong_upload_key_but_non_admin_user_gets_403(db, monkeypatch):
    monkeypatch.setattr("app.auth.get_settings", _with_groups)
    monkeypatch.setattr(
        "app.auth._decode_token",
        lambda token: {"sub": "reader-sub", "preferred_username": "reader", "groups": ["kodex-users"]},
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="fake-jwt")

    with pytest.raises(HTTPException) as exc_info:
        require_admin_or_upload_key(_request(), x_kodex_upload_key="wrong", credentials=credentials, db=db)
    assert exc_info.value.status_code == 403


def test_wrong_upload_key_but_admin_user_succeeds(db, monkeypatch):
    monkeypatch.setattr("app.auth.get_settings", _with_groups)
    monkeypatch.setattr(
        "app.auth._decode_token",
        lambda token: {"sub": "admin-sub", "preferred_username": "admin", "groups": ["kodex-users", "kodex-admins"]},
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="fake-jwt")

    require_admin_or_upload_key(_request(), x_kodex_upload_key="wrong", credentials=credentials, db=db)
    assert db.query(User).filter(User.oidc_subject == "admin-sub").one().is_admin is True
