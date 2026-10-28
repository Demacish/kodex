"""Tests for B6 (Page Manager): flag/unflag/resolve on books.py, the admin
inbox in page_flags.py, and GET /books/{id}'s deleted_page_indices.
"""

from __future__ import annotations

from app.auth import get_current_user, require_admin
from app.main import app
from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.models.user import User


def _seed_book(session_factory) -> int:
    db = session_factory()
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    book = Book(
        library_id=library.id, file_path="a.cbz", file_format=BookFormat.CBZ, file_size=1, file_mtime=0.0, page_count=20
    )
    db.add(book)
    db.commit()
    book_id = book.id
    db.close()
    return book_id


def test_flag_page_creates_flag(api):
    client, session_factory = api
    book_id = _seed_book(session_factory)

    response = client.post(f"/books/{book_id}/pages/3/flag", json={"reason": "blank"})

    assert response.status_code == 201
    body = response.json()
    assert body["page_index"] == 3
    assert body["reason"] == "blank"
    assert body["resolved"] is False


def test_flag_page_twice_updates_instead_of_duplicating(api):
    client, session_factory = api
    book_id = _seed_book(session_factory)

    first = client.post(f"/books/{book_id}/pages/3/flag", json={"reason": "blank"})
    second = client.post(f"/books/{book_id}/pages/3/flag", json={"reason": "corrupt", "note": "updated"})

    assert first.json()["id"] == second.json()["id"]
    assert second.json()["reason"] == "corrupt"
    assert second.json()["note"] == "updated"


def test_unflag_removes_own_flag(api):
    client, session_factory = api
    book_id = _seed_book(session_factory)
    client.post(f"/books/{book_id}/pages/3/flag", json={"reason": "blank"})

    response = client.delete(f"/books/{book_id}/pages/3/flag")
    assert response.status_code == 204

    flags = client.get("/page-flags").json()
    assert flags == []


def test_unflag_by_non_owner_non_admin_is_forbidden(api):
    client, session_factory = api
    book_id = _seed_book(session_factory)
    client.post(f"/books/{book_id}/pages/3/flag", json={"reason": "blank"})

    non_admin = User(id=2, oidc_subject="non-admin-sub", username="reader", is_admin=False)
    app.dependency_overrides[get_current_user] = lambda: non_admin
    del app.dependency_overrides[require_admin]

    response = client.delete(f"/books/{book_id}/pages/3/flag")
    assert response.status_code == 403


def test_unflag_unknown_flag_is_a_noop(api):
    client, session_factory = api
    book_id = _seed_book(session_factory)
    response = client.delete(f"/books/{book_id}/pages/5/flag")
    assert response.status_code == 204


def test_resolve_deleted_hides_page_from_book_detail(api):
    client, session_factory = api
    book_id = _seed_book(session_factory)
    client.post(f"/books/{book_id}/pages/3/flag", json={"reason": "blank"})

    resolve = client.post(f"/books/{book_id}/pages/3/resolve", json={"action": "deleted"})
    assert resolve.status_code == 200
    assert resolve.json()["resolved"] is True
    assert resolve.json()["resolved_action"] == "deleted"

    detail = client.get(f"/books/{book_id}").json()
    assert detail["deleted_page_indices"] == [3]


def test_resolve_kept_does_not_appear_in_deleted_page_indices(api):
    client, session_factory = api
    book_id = _seed_book(session_factory)
    client.post(f"/books/{book_id}/pages/3/flag", json={"reason": "blank"})
    client.post(f"/books/{book_id}/pages/3/resolve", json={"action": "kept"})

    detail = client.get(f"/books/{book_id}").json()
    assert detail["deleted_page_indices"] == []


def test_unresolved_flag_does_not_appear_in_deleted_page_indices(api):
    client, session_factory = api
    book_id = _seed_book(session_factory)
    client.post(f"/books/{book_id}/pages/3/flag", json={"reason": "blank"})

    detail = client.get(f"/books/{book_id}").json()
    assert detail["deleted_page_indices"] == []


def test_resolve_requires_admin(api):
    client, session_factory = api
    book_id = _seed_book(session_factory)
    client.post(f"/books/{book_id}/pages/3/flag", json={"reason": "blank"})

    non_admin = User(id=2, oidc_subject="non-admin-sub", username="reader", is_admin=False)
    app.dependency_overrides[get_current_user] = lambda: non_admin
    del app.dependency_overrides[require_admin]

    response = client.post(f"/books/{book_id}/pages/3/resolve", json={"action": "deleted"})
    assert response.status_code == 403


def test_resolve_unknown_flag_returns_404(api):
    client, session_factory = api
    book_id = _seed_book(session_factory)
    response = client.post(f"/books/{book_id}/pages/3/resolve", json={"action": "deleted"})
    assert response.status_code == 404


def test_admin_inbox_lists_unresolved_with_book_title(api):
    client, session_factory = api
    book_id = _seed_book(session_factory)
    client.post(f"/books/{book_id}/pages/3/flag", json={"reason": "corrupt", "note": "torn page"})

    response = client.get("/page-flags", params={"resolved": "false"})
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["book_id"] == book_id
    assert rows[0]["reason"] == "corrupt"
    assert rows[0]["note"] == "torn page"
    assert rows[0]["flagged_by_username"] == "test"  # see conftest.py's api fixture fake_user


def test_admin_inbox_resolved_filter_excludes_resolved_flags(api):
    client, session_factory = api
    book_id = _seed_book(session_factory)
    client.post(f"/books/{book_id}/pages/3/flag", json={"reason": "blank"})
    client.post(f"/books/{book_id}/pages/3/resolve", json={"action": "kept"})

    unresolved = client.get("/page-flags", params={"resolved": "false"}).json()
    assert unresolved == []

    all_flags = client.get("/page-flags").json()
    assert len(all_flags) == 1


def test_admin_inbox_requires_admin(api):
    client, session_factory = api
    _seed_book(session_factory)

    non_admin = User(id=2, oidc_subject="non-admin-sub", username="reader", is_admin=False)
    app.dependency_overrides[get_current_user] = lambda: non_admin
    del app.dependency_overrides[require_admin]

    response = client.get("/page-flags")
    assert response.status_code == 403
