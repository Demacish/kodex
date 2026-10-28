"""Books whose file disappears are hidden, not deleted (Book.missing_since):
the scanner hides and restores them (app/scanning/scanner.py's
_sync_missing_books), browsing endpoints leave them out, and admins can
list them and show them again (GET /books/missing, POST
/books/{id}/restore and /hide)."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

import app.scanning.scanner as scanner
from app.models.book import Book
from app.models.collection import Collection
from app.models.enums import BookFormat, CollectionType, LibraryType
from app.models.library import Library
from app.models.series import Series
from app.scanning.scanner import scan_library
from tests.conftest import _write_cbz


@pytest.fixture
def scan_env(tmp_path, monkeypatch, db_session):
    root = tmp_path / "libraries"
    (root / "serier" / "SeriesA").mkdir(parents=True)
    monkeypatch.setattr(scanner, "get_settings", lambda: SimpleNamespace(libraries_root=root))
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db_session.add(library)
    db_session.commit()
    folder = root / "serier" / "SeriesA"
    _write_cbz(folder / "SeriesA 001.cbz", 1)
    _write_cbz(folder / "SeriesA 002.cbz", 2)
    scan_library(db_session, library)
    return SimpleNamespace(db=db_session, library=library, folder=folder)


def _book(env, name: str) -> Book:
    return env.db.query(Book).filter(Book.file_path.endswith(name)).one()


def test_a_missing_file_is_hidden_and_restored_when_it_comes_back(scan_env):
    env = scan_env
    # Out of the library altogether: a file moved within it keeps its book.
    moved_away = env.folder.parent.parent.parent / "elsewhere.cbz"
    (env.folder / "SeriesA 002.cbz").rename(moved_away)

    stats = scan_library(env.db, env.library)

    hidden = _book(env, "SeriesA 002.cbz")
    assert stats.books_hidden == 1
    assert hidden.missing_since is not None
    assert _book(env, "SeriesA 001.cbz").missing_since is None

    # A second scan doesn't re-hide (or re-count) it.
    assert scan_library(env.db, env.library).books_hidden == 0

    moved_away.rename(env.folder / "SeriesA 002.cbz")
    stats = scan_library(env.db, env.library)

    assert stats.books_restored == 1
    assert _book(env, "SeriesA 002.cbz").missing_since is None


def test_an_empty_library_folder_hides_nothing(scan_env):
    env = scan_env
    for path in env.folder.iterdir():
        path.unlink()

    stats = scan_library(env.db, env.library)

    assert stats.books_hidden == 0
    assert any("döljer inget" in error for error in stats.errors)
    assert all(book.missing_since is None for book in env.db.query(Book).all())


def test_a_book_shown_again_by_hand_stays_visible_until_its_file_returns(scan_env):
    env = scan_env
    (env.folder / "SeriesA 002.cbz").unlink()
    scan_library(env.db, env.library)
    book = _book(env, "SeriesA 002.cbz")
    book.missing_since = None
    book.keep_visible_when_missing = True
    env.db.commit()

    assert scan_library(env.db, env.library).books_hidden == 0
    assert _book(env, "SeriesA 002.cbz").missing_since is None

    _write_cbz(env.folder / "SeriesA 002.cbz", 2)
    scan_library(env.db, env.library)
    assert _book(env, "SeriesA 002.cbz").keep_visible_when_missing is False


# --- API -------------------------------------------------------------------


@pytest.fixture
def seeded(api):
    """A series with one visible and one hidden book, both in a manual
    collection and both with reading progress."""
    client, session_factory = api
    db = session_factory()
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    series = Series(library_id=library.id, title="SeriesA", sort_title="seriesa", path="SeriesA")
    lonely = Series(library_id=library.id, title="Bara saknad", sort_title="bara saknad", path="Bara")
    db.add_all([series, lonely])
    db.flush()

    def book(path, series_id, number, missing):
        b = Book(
            library_id=library.id,
            series_id=series_id,
            file_path=path,
            file_format=BookFormat.CBZ,
            file_size=1,
            file_mtime=0.0,
            number=number,
            missing_since=dt.datetime(2026, 9, 30, tzinfo=dt.UTC) if missing else None,
        )
        db.add(b)
        db.flush()
        return b.id

    visible_id = book("SeriesA/001.cbz", series.id, 1, False)
    hidden_id = book("SeriesA/002.cbz", series.id, 2, True)
    lonely_id = book("Bara/001.cbz", lonely.id, 1, True)
    collection = Collection(name="Läslista", collection_type=CollectionType.MANUAL)
    collection.books = [db.get(Book, visible_id), db.get(Book, hidden_id)]
    db.add(collection)
    db.commit()
    ids = SimpleNamespace(
        library=library.id,
        series=series.id,
        lonely=lonely.id,
        visible=visible_id,
        hidden=hidden_id,
        lonely_book=lonely_id,
        collection=collection.id,
    )
    db.close()
    for book_id in (visible_id, hidden_id):
        client.put(f"/books/{book_id}/progress", json={"position": "0", "progress_percent": 10})
    return client, ids


def test_hidden_books_are_left_out_of_browsing(seeded):
    client, ids = seeded

    assert [b["id"] for b in client.get(f"/books?series_id={ids.series}").json()] == [ids.visible]
    series = {s["id"]: s for s in client.get(f"/series?library_id={ids.library}").json()}
    assert set(series) == {ids.series}  # the series with only a hidden book is gone
    assert series[ids.series]["book_count"] == 1
    assert client.get(f"/series/{ids.series}").json()["book_count"] == 1
    assert [letter["count"] for letter in client.get(f"/series/letters?library_id={ids.library}").json()] == [1]
    assert [i["book_id"] for i in client.get("/me/continue-reading").json()] == [ids.visible]
    assert [b["id"] for b in client.get(f"/collections/{ids.collection}/books").json()] == [ids.visible]
    # Still reachable directly, flagged as missing.
    assert client.get(f"/books/{ids.hidden}").json()["missing_since"] is not None


def test_reordering_a_collection_keeps_hidden_books_after_the_visible_ones(seeded):
    client, ids = seeded
    assert client.put(f"/collections/{ids.collection}/order", json=[ids.visible]).status_code == 204
    # Including the hidden one (which the client can't see) is rejected.
    assert client.put(f"/collections/{ids.collection}/order", json=[ids.hidden, ids.visible]).status_code == 400


def test_admin_lists_restores_and_hides_again(seeded):
    client, ids = seeded

    missing = client.get("/books/missing").json()
    assert {m["id"] for m in missing} == {ids.hidden, ids.lonely_book}
    row = next(m for m in missing if m["id"] == ids.hidden)
    assert row["library_name"] == "Serier"
    assert row["series_title"] == "SeriesA"
    assert row["keep_visible_when_missing"] is False

    # Only a book restored by hand can be hidden again by hand.
    assert client.post(f"/books/{ids.visible}/hide").status_code == 409

    restored = client.post(f"/books/{ids.hidden}/restore").json()
    assert restored["missing_since"] is None
    assert restored["keep_visible_when_missing"] is True
    assert ids.hidden in [b["id"] for b in client.get(f"/books?series_id={ids.series}").json()]
    # Still listed for the admin — its file is still gone.
    assert ids.hidden in [m["id"] for m in client.get("/books/missing").json()]

    hidden_again = client.post(f"/books/{ids.hidden}/hide").json()
    assert hidden_again["missing_since"] is not None
    assert ids.hidden not in [b["id"] for b in client.get(f"/books?series_id={ids.series}").json()]


def test_search_leaves_out_hidden_books(seeded, api):
    from app.models.content_index import ContentIndexEntry
    from app.models.metadata import BookMetadata

    client, ids = seeded
    _, session_factory = api
    with session_factory() as db:
        for book_id in (ids.visible, ids.hidden):
            db.add(BookMetadata(book_id=book_id, title="Gemensam titel", sort_title="gemensam titel"))
            db.add(ContentIndexEntry(book_id=book_id, position="1", text="ett gemensamt ord"))
        db.commit()
    assert [h["book_id"] for h in client.get("/search/books?q=gemensam").json()] == [ids.visible]
    assert [h["book_id"] for h in client.get("/search/fulltext?q=gemensamt").json()] == [ids.visible]
