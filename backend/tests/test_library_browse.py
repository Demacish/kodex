"""Tests for GET /libraries/{id}/browse — the file-browser data source
behind LibraryFileUpload.tsx's admin folder navigation (ReadMeABook-
inspired, see claude/omnibus-och-ai-forbattringar.md). Read-only — never
writes to disk, unlike test_library_upload.py's endpoint.
"""

from __future__ import annotations

import app.api.routes.libraries as libraries_module
from app.auth import get_current_user, require_admin
from app.config import Settings
from app.main import app
from app.models.enums import LibraryType
from app.models.library import Library
from app.models.user import User


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


def test_browse_root_lists_subfolders_and_files(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    root = tmp_path / "serier"
    (root / "Absolute Corvid").mkdir(parents=True)
    (root / "Absolute Corvid" / "001.cbz").write_bytes(b"x")
    (root / "Absolute Corvid" / "002.cbz").write_bytes(b"x")
    (root / "loose.cbz").write_bytes(b"x")
    (root / "notes.txt").write_bytes(b"x")  # not an importable extension — must be excluded

    client, session_factory = api
    library_id = _seed_library(session_factory)

    response = client.get(f"/libraries/{library_id}/browse")

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == ""
    assert body["breadcrumbs"] == []
    names = {e["name"]: e for e in body["entries"]}
    assert names["Absolute Corvid"] == {"name": "Absolute Corvid", "is_dir": True, "book_count": 2}
    assert names["loose.cbz"] == {"name": "loose.cbz", "is_dir": False, "book_count": None}
    assert "notes.txt" not in names


def test_browse_missing_root_returns_empty_listing(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)  # tmp_path/serier is never created
    client, session_factory = api
    library_id = _seed_library(session_factory)

    response = client.get(f"/libraries/{library_id}/browse")

    assert response.status_code == 200
    assert response.json() == {"path": "", "breadcrumbs": [], "entries": []}


def test_browse_descends_into_subfolder(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    nested = tmp_path / "serier" / "Absolute Corvid"
    nested.mkdir(parents=True)
    (nested / "001.cbz").write_bytes(b"x")

    client, session_factory = api
    library_id = _seed_library(session_factory)

    response = client.get(f"/libraries/{library_id}/browse", params={"path": "Absolute Corvid"})

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == "Absolute Corvid"
    assert body["breadcrumbs"] == ["Absolute Corvid"]
    assert [e["name"] for e in body["entries"]] == ["001.cbz"]


def test_browse_hides_dotfiles(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    root = tmp_path / "serier"
    root.mkdir(parents=True)
    (root / ".DS_Store").write_bytes(b"x")
    (root / ".git").mkdir()

    client, session_factory = api
    library_id = _seed_library(session_factory)

    response = client.get(f"/libraries/{library_id}/browse")

    assert response.json()["entries"] == []


def test_browse_rejects_path_escaping_library(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    client, session_factory = api
    library_id = _seed_library(session_factory)

    response = client.get(f"/libraries/{library_id}/browse", params={"path": "../../etc"})
    assert response.status_code == 400


def test_browse_unknown_subfolder_404s(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    (tmp_path / "serier").mkdir(parents=True)
    client, session_factory = api
    library_id = _seed_library(session_factory)

    response = client.get(f"/libraries/{library_id}/browse", params={"path": "Does Not Exist"})
    assert response.status_code == 404


def test_browse_unknown_library_404s(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    client, _ = api

    response = client.get("/libraries/999999/browse")
    assert response.status_code == 404


def test_browse_requires_admin(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    client, session_factory = api
    library_id = _seed_library(session_factory)

    non_admin = User(id=2, oidc_subject="non-admin-sub", username="reader", is_admin=False)
    app.dependency_overrides[get_current_user] = lambda: non_admin
    del app.dependency_overrides[require_admin]

    response = client.get(f"/libraries/{library_id}/browse")
    assert response.status_code == 403
