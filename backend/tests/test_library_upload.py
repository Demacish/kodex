"""Tests for POST /libraries/{id}/upload — B7's admin-only manual file
upload into a library folder + auto-rescan trigger. See
app/api/routes/libraries.py's upload_book_file.
"""

from __future__ import annotations

from fastapi import HTTPException

import app.api.routes.libraries as libraries_module
from app.auth import require_admin_or_upload_key
from app.config import Settings
from app.main import app
from app.models.enums import LibraryType
from app.models.library import Library


def _seed_library(session_factory, *, path: str = "serier") -> int:
    db = session_factory()
    library = Library(name="Serier", path=path, library_type=LibraryType.COMICS)
    db.add(library)
    db.commit()
    library_id = library.id
    db.close()
    return library_id


def _patch_libraries_root(monkeypatch, tmp_path):
    monkeypatch.setattr(libraries_module, "get_settings", lambda: Settings(libraries_root=tmp_path))


class _FakeJob:
    id = "upload-scan-job-id"


class _FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, func, *args, **kwargs):
        self.calls.append((func, args))
        return _FakeJob()


def test_upload_writes_file_and_triggers_scan(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    fake_queue = _FakeQueue()
    monkeypatch.setattr(libraries_module, "get_scan_queue", lambda: fake_queue)

    client, session_factory = api
    library_id = _seed_library(session_factory)

    response = client.post(
        f"/libraries/{library_id}/upload",
        files={"file": ("Absolute Corvid 001.cbz", b"fake-cbz-bytes", "application/octet-stream")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["path"] == "Absolute Corvid 001.cbz"
    assert body["job_id"] == "upload-scan-job-id"
    assert (tmp_path / "serier" / "Absolute Corvid 001.cbz").read_bytes() == b"fake-cbz-bytes"
    assert len(fake_queue.calls) == 1


def test_upload_with_subfolder_creates_nested_path(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    monkeypatch.setattr(libraries_module, "get_scan_queue", lambda: _FakeQueue())

    client, session_factory = api
    library_id = _seed_library(session_factory)

    response = client.post(
        f"/libraries/{library_id}/upload",
        data={"subfolder": "Absolute Corvid"},
        files={"file": ("001.cbz", b"bytes", "application/octet-stream")},
    )

    assert response.status_code == 201
    assert response.json()["path"] == "Absolute Corvid/001.cbz"
    assert (tmp_path / "serier" / "Absolute Corvid" / "001.cbz").is_file()


def test_upload_rejects_subfolder_escaping_library(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    client, session_factory = api
    library_id = _seed_library(session_factory)

    response = client.post(
        f"/libraries/{library_id}/upload",
        data={"subfolder": "../../etc"},
        files={"file": ("x.cbz", b"bytes", "application/octet-stream")},
    )

    assert response.status_code == 400


def test_upload_rejects_unsupported_extension(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    client, session_factory = api
    library_id = _seed_library(session_factory)

    response = client.post(
        f"/libraries/{library_id}/upload",
        files={"file": ("malware.exe", b"bytes", "application/octet-stream")},
    )

    assert response.status_code == 400


def test_upload_rejects_file_too_large(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    monkeypatch.setattr(libraries_module, "_MAX_UPLOAD_BYTES", 10)

    client, session_factory = api
    library_id = _seed_library(session_factory)

    response = client.post(
        f"/libraries/{library_id}/upload",
        files={"file": ("x.cbz", b"this-is-more-than-ten-bytes", "application/octet-stream")},
    )

    assert response.status_code == 400


def test_upload_rejects_when_file_already_exists(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    monkeypatch.setattr(libraries_module, "get_scan_queue", lambda: _FakeQueue())

    client, session_factory = api
    library_id = _seed_library(session_factory)

    first = client.post(
        f"/libraries/{library_id}/upload", files={"file": ("dup.cbz", b"one", "application/octet-stream")}
    )
    assert first.status_code == 201

    second = client.post(
        f"/libraries/{library_id}/upload", files={"file": ("dup.cbz", b"two", "application/octet-stream")}
    )
    assert second.status_code == 409
    # Original content untouched.
    assert (tmp_path / "serier" / "dup.cbz").read_bytes() == b"one"


def test_upload_requires_admin(api, tmp_path, monkeypatch):
    """The endpoint itself just needs to propagate a 403 from its auth
    dependency correctly — require_admin_or_upload_key's own OR-logic
    (upload-key header vs. falling back to a real admin check) is unit-
    tested directly in test_auth_upload_key.py instead, since it calls
    get_current_user/require_admin as plain Python functions (see its own
    docstring for why), which dependency_overrides can't reach through
    the HTTP/TestClient layer the way it can a route's own Depends().
    """
    _patch_libraries_root(monkeypatch, tmp_path)
    client, session_factory = api
    library_id = _seed_library(session_factory)

    def _raise_403():
        raise HTTPException(status_code=403, detail="Admin access required")

    app.dependency_overrides[require_admin_or_upload_key] = _raise_403

    response = client.post(
        f"/libraries/{library_id}/upload", files={"file": ("x.cbz", b"bytes", "application/octet-stream")}
    )
    assert response.status_code == 403


def test_upload_unknown_library_returns_404(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    client, _ = api

    response = client.post("/libraries/999999/upload", files={"file": ("x.cbz", b"bytes", "application/octet-stream")})
    assert response.status_code == 404


def test_upload_with_rescan_false_skips_the_scan(api, tmp_path, monkeypatch):
    # Another Kodex server copying a batch (kodex/delivery/federation) asks for one scan
    # at the end instead of one per file.
    _patch_libraries_root(monkeypatch, tmp_path)
    fake_queue = _FakeQueue()
    monkeypatch.setattr(libraries_module, "get_scan_queue", lambda: fake_queue)

    client, session_factory = api
    library_id = _seed_library(session_factory)

    response = client.post(
        f"/libraries/{library_id}/upload",
        data={"rescan": "false"},
        files={"file": ("002.cbz", b"bytes", "application/octet-stream")},
    )

    assert response.status_code == 201
    assert response.json()["job_id"] is None
    assert fake_queue.calls == []


def test_upload_into_an_unwritable_folder_says_so(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    monkeypatch.setattr(libraries_module, "get_scan_queue", lambda: _FakeQueue())

    def refuse(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied", str(self))

    client, session_factory = api
    library_id = _seed_library(session_factory)
    monkeypatch.setattr("pathlib.Path.mkdir", refuse)
    response = client.post(
        f"/libraries/{library_id}/upload",
        data={"subfolder": "New"},
        files={"file": ("Absolute Corvid 001.cbz", b"fake-cbz-bytes", "application/octet-stream")},
    )
    assert response.status_code == 409
    assert "permissions" in response.json()["detail"]
