"""Bookmarks (kodex.reading.bookmarks): saved under the client's own id, so
sending one twice keeps one; listed per book in reading order; removed
twice without an error; and each user's are their own."""

from __future__ import annotations

import pytest

from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.models.user import User
from kodex.reading.models import Bookmark

FIRST = "3f0c2a8e-1b7d-4c55-9e0a-6d2f4b8c1a01"
SECOND = "3f0c2a8e-1b7d-4c55-9e0a-6d2f4b8c1a02"
THIRD = "3f0c2a8e-1b7d-4c55-9e0a-6d2f4b8c1a03"


@pytest.fixture
def books(api):
    client, session_factory = api
    with session_factory() as db:
        library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
        db.add(library)
        db.flush()
        ids = []
        for number in (1, 2):
            book = Book(library_id=library.id, file_path=f"s/{number}.cbz", file_format=BookFormat.CBZ,
                        file_size=1, file_mtime=0.0, number=float(number))  # fmt: skip
            db.add(book)
            db.flush()
            ids.append(book.id)
        db.commit()
    return client, session_factory, ids


def _mark(book_id: int, page: int, **extra):
    return {"book_id": book_id, "position": str(page), "locator_kind": "page", "progress_percent": page * 10.0, **extra}


def test_a_bookmark_is_saved_once_however_often_it_is_sent(books):
    client, _, (book, _) = books
    for _ in range(2):
        response = client.put(f"/api/bookmarks/{FIRST}", json=_mark(book, 4, chapter="Den långa natten"))
        assert response.status_code == 200, response.text
    listed = client.get("/api/bookmarks").json()
    assert [(b["id"], b["position"], b["chapter"]) for b in listed] == [(FIRST, "4", "Den långa natten")]


def test_sending_it_again_changes_its_note(books):
    client, _, (book, _) = books
    client.put(f"/api/bookmarks/{FIRST}", json=_mark(book, 4))
    changed = client.put(f"/api/bookmarks/{FIRST}", json=_mark(book, 4, note="Kartan"))
    assert changed.json()["note"] == "Kartan"


def test_the_list_is_per_book_in_reading_order(books):
    client, _, (book, other) = books
    client.put(f"/api/bookmarks/{FIRST}", json=_mark(book, 7))
    client.put(f"/api/bookmarks/{SECOND}", json=_mark(book, 2))
    client.put(f"/api/bookmarks/{THIRD}", json=_mark(other, 1))
    assert [b["position"] for b in client.get("/api/bookmarks", params={"book_id": book}).json()] == ["2", "7"]
    assert len(client.get("/api/bookmarks").json()) == 3


def test_an_upper_case_id_is_the_same_bookmark(books):
    client, _, (book, _) = books
    client.put(f"/api/bookmarks/{FIRST.upper()}", json=_mark(book, 1))
    assert client.delete(f"/api/bookmarks/{FIRST}").status_code == 204
    assert client.get("/api/bookmarks").json() == []


def test_removing_it_twice_is_fine(books):
    client, _, (book, _) = books
    client.put(f"/api/bookmarks/{FIRST}", json=_mark(book, 1))
    assert client.delete(f"/api/bookmarks/{FIRST}").status_code == 204
    assert client.delete(f"/api/bookmarks/{FIRST}").status_code == 204
    assert client.get("/api/bookmarks").json() == []


def test_a_book_that_isnt_there_or_a_bad_id_is_refused(books):
    client, _, (book, _) = books
    assert client.put(f"/api/bookmarks/{FIRST}", json=_mark(999_999, 1)).status_code == 404
    assert client.put("/api/bookmarks/not-a-uuid", json=_mark(book, 1)).status_code == 422
    assert client.put(f"/api/bookmarks/{FIRST}", json={**_mark(book, 1), "locator_kind": "chapter"}).status_code == 422


def test_another_users_bookmarks_are_theirs(books):
    client, session_factory, (book, _) = books
    with session_factory() as db:
        other = User(oidc_subject="other-sub", username="bertil")
        db.add(other)
        db.flush()
        db.add(Bookmark(id=FIRST, user_id=other.id, book_id=book, position="3", locator_kind="page", progress_percent=30))
        db.commit()
    assert client.get("/api/bookmarks").json() == []
    assert client.put(f"/api/bookmarks/{FIRST}", json=_mark(book, 5)).status_code == 409
    assert client.delete(f"/api/bookmarks/{FIRST}").status_code == 204
    with session_factory() as db:
        assert db.get(Bookmark, FIRST) is not None
