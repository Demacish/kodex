"""API-level tests for B9's POST /series/{id}/export and POST
/libraries/{id}/import-series-json. See tests/test_series_json.py for
the underlying module's own unit tests.
"""

from __future__ import annotations

import app.api.routes.libraries as libraries_module
import app.api.routes.series as series_module
from app.auth import get_current_user, require_admin
from app.config import Settings
from app.main import app
from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.models.metadata import BookMetadata
from app.models.series import Series
from app.models.user import User


def _seed_series(session_factory, *, folder: str = "Absolute Corvid") -> tuple[int, int]:
    db = session_factory()
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    series = Series(library_id=library.id, title="Absolute Corvid", sort_title="Absolute Corvid", path=folder)
    db.add(series)
    db.flush()
    book = Book(
        library_id=library.id,
        series_id=series.id,
        file_path=f"{folder}/001.cbz",
        file_format=BookFormat.CBZ,
        file_size=1,
        file_mtime=0.0,
        number=1.0,
    )
    db.add(book)
    db.flush()
    db.add(
        BookMetadata(book_id=book.id, title="Absolute Corvid #1", sort_title="Absolute Corvid #1", authors=["Writer"])
    )
    db.commit()
    library_id, series_id = library.id, series.id
    db.close()
    return library_id, series_id


def _patch_libraries_root(monkeypatch, tmp_path):
    monkeypatch.setattr(series_module, "get_settings", lambda: Settings(libraries_root=tmp_path))
    monkeypatch.setattr(libraries_module, "get_settings", lambda: Settings(libraries_root=tmp_path))


def test_export_series_writes_file_and_stamps_timestamp(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    client, session_factory = api
    _library_id, series_id = _seed_series(session_factory)

    response = client.post(f"/series/{series_id}/export")
    assert response.status_code == 200
    assert (tmp_path / "serier" / "Absolute Corvid" / "series.json").is_file()

    series_out = client.get(f"/series/{series_id}").json()
    assert series_out["metadata_exported_at"] is not None


def test_export_series_requires_admin(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    client, session_factory = api
    _library_id, series_id = _seed_series(session_factory)

    non_admin = User(id=2, oidc_subject="non-admin-sub", username="reader", is_admin=False)
    app.dependency_overrides[get_current_user] = lambda: non_admin
    del app.dependency_overrides[require_admin]

    response = client.post(f"/series/{series_id}/export")
    assert response.status_code == 403


def test_export_unknown_series_returns_404(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    client, _ = api
    assert client.post("/series/999999/export").status_code == 404


def test_import_series_json_updates_books(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    client, session_factory = api
    library_id, series_id = _seed_series(session_factory)

    client.post(f"/series/{series_id}/export")

    db = session_factory()
    book = db.query(Book).filter(Book.library_id == library_id).one()
    book_id = book.id
    book.book_metadata.authors = []
    db.add(book.book_metadata)
    db.commit()
    db.close()

    response = client.post(f"/libraries/{library_id}/import-series-json")
    assert response.status_code == 200
    body = response.json()
    assert body["files_found"] == 1
    assert body["books_updated"] == 1
    assert body["books_not_found"] == 0

    book_out = client.get(f"/books/{book_id}").json()
    assert book_out["book_metadata"]["authors"] == ["Writer"]


def test_import_series_json_requires_admin(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    client, session_factory = api
    library_id, _series_id = _seed_series(session_factory)

    non_admin = User(id=2, oidc_subject="non-admin-sub", username="reader", is_admin=False)
    app.dependency_overrides[get_current_user] = lambda: non_admin
    del app.dependency_overrides[require_admin]

    response = client.post(f"/libraries/{library_id}/import-series-json")
    assert response.status_code == 403


def test_import_series_json_unknown_library_returns_404(api, tmp_path, monkeypatch):
    _patch_libraries_root(monkeypatch, tmp_path)
    client, _ = api
    assert client.post("/libraries/999999/import-series-json").status_code == 404
