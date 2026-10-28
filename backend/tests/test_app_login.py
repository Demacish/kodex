"""Logging an app in (kodex.core.auth.apps): with the password, with the
second step, or approved through the browser with a code and verifier;
and the downloads an app makes: resumable with Range, verified with the
file's SHA-256."""

from __future__ import annotations

import base64
import hashlib
import secrets
import time

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from kodex.core.auth import totp
from tests import test_auth as base

settings, client = base.settings, base.client
PASSWORD, _csrf, _login, _make_user = base.PASSWORD, base._csrf, base._login, base._make_user


def _app() -> TestClient:
    return TestClient(app, base_url="https://kodex.test")


def _bearer(key: str) -> dict[str, str]:
    return {"authorization": f"Bearer {key}"}


def test_an_app_logs_in_with_the_password(client):
    _make_user("anna")
    phone = _app()
    assert (
        phone.post(
            "/api/auth/app/login", json={"username": "anna", "password": "nope", "device_name": "Pixel"}
        ).status_code
        == 401
    )
    answer = phone.post(
        "/api/auth/app/login", json={"username": "anna", "password": PASSWORD, "device_name": "Pixel 9"}
    )
    key = answer.json()["key"]
    assert key["name"] == "App: Pixel 9" and key["key"].startswith("kdx_")
    me = phone.get("/api/auth/me", headers=_bearer(key["key"])).json()
    assert (me["username"], me["auth_method"]) == ("anna", "api_key")
    assert phone.post("/api/auth/app/logout", headers=_bearer(key["key"])).status_code == 204
    assert phone.get("/api/auth/me", headers=_bearer(key["key"])).status_code == 401


def test_an_app_takes_the_second_step(client):
    _make_user("anna")
    _login(client, "anna")
    secret = client.post("/api/auth/totp", headers=_csrf(client)).json()["secret"]
    step = totp.step_at(time.time())
    client.post("/api/auth/totp/confirm", json={"code": totp.code_at(secret, step)}, headers=_csrf(client))
    phone = _app()
    started = phone.post(
        "/api/auth/app/login", json={"username": "anna", "password": PASSWORD, "device_name": "Pixel"}
    ).json()
    assert started["key"] is None and started["second_step"]["methods"] == ["totp", "recovery"]
    ticket = started["second_step"]["ticket"]
    assert phone.post("/api/auth/app/second-step", json={"ticket": ticket, "code": "000000"}).status_code == 401
    done = phone.post("/api/auth/app/second-step", json={"ticket": ticket, "code": totp.code_at(secret, step + 1)})
    assert done.status_code == 200 and done.json()["name"] == "App: Pixel"


def test_an_app_is_approved_through_the_browser(client):
    _make_user("anna")
    _login(client, "anna")
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    approved = client.post("/api/auth/app/approve", json={"device_name": "Läsplatta", "challenge": challenge},
                           headers=_csrf(client))  # fmt: skip
    assert approved.status_code == 200
    code = approved.json()["code"]
    phone = _app()
    assert (
        phone.post("/api/auth/app/token", json={"code": code, "verifier": secrets.token_urlsafe(48)}).status_code == 401
    )
    # The code went with the failed try: approving again is the way.
    approved = client.post("/api/auth/app/approve", json={"device_name": "Läsplatta", "challenge": challenge},
                           headers=_csrf(client)).json()  # fmt: skip
    key = phone.post("/api/auth/app/token", json={"code": approved["code"], "verifier": verifier}).json()
    assert key["name"] == "App: Läsplatta"
    assert phone.get("/api/auth/me", headers=_bearer(key["key"])).json()["username"] == "anna"
    again = phone.post("/api/auth/app/token", json={"code": approved["code"], "verifier": verifier})
    assert again.status_code == 401


def test_approving_needs_the_web_session(client):
    _make_user("anna")
    phone = _app()
    key = phone.post("/api/auth/app/login", json={"username": "anna", "password": PASSWORD, "device_name": "P"}).json()[
        "key"
    ]
    challenge = "A" * 43
    refused = phone.post("/api/auth/app/approve", json={"device_name": "X", "challenge": challenge},
                         headers=_bearer(key["key"]))  # fmt: skip
    assert refused.status_code == 403


def test_downloads_resume_and_verify(client, tmp_path, settings):
    root = tmp_path / "libraries"
    (root / "serier").mkdir(parents=True)
    data = bytes(range(256)) * 40
    (root / "serier" / "a.cbz").write_bytes(data)
    settings(libraries_root=str(root))
    _make_user("anna")
    with SessionLocal() as db:
        library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
        db.add(library)
        db.flush()
        book = Book(library_id=library.id, file_path="a.cbz", file_format=BookFormat.CBZ, file_size=len(data),
                    file_mtime=0.0)  # fmt: skip
        db.add(book)
        db.commit()
        book_id = book.id
    phone = _app()
    key = phone.post("/api/auth/app/login", json={"username": "anna", "password": PASSWORD, "device_name": "P"}).json()[
        "key"
    ]
    part = phone.get(f"/api/books/{book_id}/file", headers={**_bearer(key["key"]), "range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == data[100:200]
    digest = phone.get(f"/api/books/{book_id}/digest", headers=_bearer(key["key"])).json()
    assert digest == {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    (root / "serier" / "a.cbz").write_bytes(data[::-1] + b"!")
    changed = phone.get(f"/api/books/{book_id}/digest", headers=_bearer(key["key"])).json()
    assert changed["sha256"] == hashlib.sha256(data[::-1] + b"!").hexdigest()
