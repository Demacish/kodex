"""Delta sync for apps (kodex.core.sync): everything from cursor 0, then
only what changed, deletions and missing files as tombstones, a page at
a time, collections the user may see, reading positions with their own
cursor, and a reset for a cursor the server has never reached."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import text

from app.models.book import Book
from app.models.collection import Collection, collection_books
from app.models.enums import BookFormat, CollectionType, LibraryType
from app.models.library import Library
from app.models.metadata import BookMetadata
from app.models.series import Series
from app.models.user import User
from kodex.core import sync


@pytest.fixture
def catalog(api):
    client, session_factory = api
    with session_factory() as db:
        library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
        db.add(library)
        db.flush()
        series = Series(library_id=library.id, title="Stjärnhavet", sort_title="Stjärnhavet", path="s")
        db.add(series)
        db.flush()
        ids = {"library": library.id, "series": series.id}
        for number in (1, 2):
            book = Book(library_id=library.id, series_id=series.id, file_path=f"s/{number}.cbz",
                        file_format=BookFormat.CBZ, file_size=1, file_mtime=0.0, number=float(number))  # fmt: skip
            db.add(book)
            db.flush()
            db.add(BookMetadata(book_id=book.id, title=f"Stjärnhavet #{number}", sort_title=f"{number}"))
            ids[f"book{number}"] = book.id
        db.commit()
    return client, session_factory, ids


def _changes(client, since=0, progress_since=0, **params):
    response = client.get("/api/sync/changes", params={"since": since, "progress_since": progress_since, **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_cursor_zero_brings_everything_then_nothing(catalog):
    client, _, ids = catalog
    first = _changes(client)
    assert [lib["id"] for lib in first["libraries"]] == [ids["library"]]
    assert [s["id"] for s in first["series"]] == [ids["series"]] and first["series"][0]["book_count"] == 2
    assert sorted(b["id"] for b in first["books"]) == [ids["book1"], ids["book2"]]
    assert first["books"][0]["book_metadata"]["title"].startswith("Stjärnhavet #")
    assert first["more"] is False and first["reset"] is False
    again = _changes(client, since=first["cursor"])
    assert (again["books"], again["series"], again["deleted"]["books"]) == ([], [], [])
    assert again["cursor"] == first["cursor"]


def test_changes_and_deletions_come_once(catalog):
    client, session_factory, ids = catalog
    cursor = _changes(client)["cursor"]
    with session_factory() as db:
        db.query(BookMetadata).filter(BookMetadata.book_id == ids["book1"]).update({"title": "Ny titel"})
        db.get(Book, ids["book2"]).missing_since = dt.datetime.now(dt.UTC)
        db.commit()
    changed = _changes(client, since=cursor)
    assert [b["book_metadata"]["title"] for b in changed["books"]] == ["Ny titel"]
    assert changed["deleted"]["books"] == [ids["book2"]]  # a missing file is gone for the app
    with session_factory() as db:
        db.delete(db.get(Series, ids["series"]))
        db.commit()
    gone = _changes(client, since=changed["cursor"])
    assert gone["deleted"]["series"] == [ids["series"]]
    assert sorted(gone["deleted"]["books"]) == [ids["book1"], ids["book2"]]


def test_an_unchanged_write_is_no_change(catalog):
    client, session_factory, ids = catalog
    cursor = _changes(client)["cursor"]
    with session_factory() as db:
        db.execute(text("UPDATE books SET file_size = file_size WHERE id = :id"), {"id": ids["book1"]})
        db.commit()
    assert _changes(client, since=cursor)["books"] == []


def test_a_long_history_comes_in_pages(catalog):
    client, _, _ = catalog
    first = _changes(client, limit=2)
    assert first["more"] is True and len(first["libraries"]) + len(first["series"]) + len(first["books"]) == 2
    rest = _changes(client, since=first["cursor"], limit=2)
    assert rest["more"] is False
    assert len(rest["libraries"]) + len(rest["series"]) + len(rest["books"]) == 2


def test_only_the_users_and_shared_collections_come(catalog):
    client, session_factory, ids = catalog
    with session_factory() as db:
        other = User(id=2, oidc_subject="sub-bo", username="bo", role="user")
        db.add(other)
        db.flush()
        shared = Collection(name="Läslista", collection_type=CollectionType.MANUAL)
        private = Collection(name="Bos hemliga", collection_type=CollectionType.MANUAL, owner_user_id=other.id)
        db.add_all([shared, private])
        db.flush()
        db.execute(collection_books.insert().values(collection_id=shared.id, book_id=ids["book2"], position=0))
        db.execute(collection_books.insert().values(collection_id=shared.id, book_id=ids["book1"], position=1))
        db.commit()
    found = _changes(client)["collections"]
    assert [(c["name"], c["book_ids"]) for c in found] == [("Läslista", [ids["book2"], ids["book1"]])]


def test_positions_come_with_their_own_cursor(catalog):
    client, _, ids = catalog
    client.put(f"/api/books/{ids['book1']}/progress", json={"position": "3", "progress_percent": 30})
    first = _changes(client)
    assert [(p["book_id"], p["position"]) for p in first["progress"]] == [(ids["book1"], "3")]
    assert _changes(client, since=first["cursor"], progress_since=first["progress_cursor"])["progress"] == []
    client.put(f"/api/books/{ids['book1']}/progress", json={"position": "5", "progress_percent": 50})
    later = _changes(client, since=first["cursor"], progress_since=first["progress_cursor"])
    assert [p["position"] for p in later["progress"]] == ["5"]


def test_a_cursor_from_another_history_resets(catalog):
    client, _, _ = catalog
    answer = _changes(client, since=10_000_000)
    assert (answer["reset"], answer["cursor"]) == (True, 0)


def test_compaction_keeps_the_newest_row_per_entity(catalog):
    client, session_factory, ids = catalog
    with session_factory() as db:
        for title in ("a", "b", "c"):
            db.query(BookMetadata).filter(BookMetadata.book_id == ids["book1"]).update({"title": title})
            db.commit()
        assert sync.compact(db) >= 3
        db.commit()
    books = {b["id"]: b for b in _changes(client)["books"]}
    assert books[ids["book1"]]["book_metadata"]["title"] == "c"
