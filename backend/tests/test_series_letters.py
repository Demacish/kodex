"""Tests for GET /series/letters — the alphabet jump bar's data source
(A3). See app/api/routes/series.py's list_series_letters.
"""

from __future__ import annotations

from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.models.series import Series


def _seed_series(
    session_factory, *, title: str, sort_title: str | None = None, is_following: bool = False, with_book: bool = True
) -> int:
    db = session_factory()
    library = Library(name=f"Lib-{title}", path=f"lib-{title}", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    series = Series(
        library_id=library.id,
        title=title,
        sort_title=sort_title or title,
        path=title,
        is_following=is_following,
    )
    db.add(series)
    db.flush()
    if with_book:
        book = Book(
            library_id=library.id,
            series_id=series.id,
            file_path=f"{title}/1.cbz",
            file_format=BookFormat.CBZ,
            file_size=1,
            file_mtime=0.0,
            number=1,
        )
        db.add(book)
    db.commit()
    series_id = series.id
    db.close()
    return series_id


def test_letters_groups_by_first_character(api):
    client, session_factory = api
    _seed_series(session_factory, title="Absolute Corvid")
    _seed_series(session_factory, title="Absolute Skyrider")
    _seed_series(session_factory, title="Bramble")

    response = client.get("/series/letters")

    assert response.status_code == 200
    by_letter = {row["letter"]: row for row in response.json()}
    assert by_letter["A"]["count"] == 2
    assert by_letter["A"]["offset"] == 0
    assert by_letter["B"]["count"] == 1
    assert by_letter["B"]["offset"] == 2


def test_letters_non_alphabetic_sort_title_buckets_under_hash(api):
    client, session_factory = api
    _seed_series(session_factory, title="1994", sort_title="1994")
    _seed_series(session_factory, title="Zzz")

    by_letter = {row["letter"]: row for row in client.get("/series/letters").json()}
    assert by_letter["#"]["count"] == 1
    assert by_letter["Z"]["count"] == 1


def test_letters_excludes_empty_series(api):
    client, session_factory = api
    _seed_series(session_factory, title="Has Books")
    _seed_series(session_factory, title="Empty Series", with_book=False)

    by_letter = {row["letter"]: row for row in client.get("/series/letters").json()}
    assert by_letter["H"]["count"] == 1
    assert "E" not in by_letter


def test_letters_filters_by_following(api):
    client, session_factory = api
    _seed_series(session_factory, title="Followed", is_following=True)
    _seed_series(session_factory, title="Zebra", is_following=False)

    by_letter = {row["letter"]: row for row in client.get("/series/letters?following=true").json()}
    assert set(by_letter.keys()) == {"F"}


def test_letters_filters_by_library_id(api):
    client, session_factory = api
    series_a = _seed_series(session_factory, title="A Series")
    _seed_series(session_factory, title="B Series")

    db = session_factory()
    library_id = db.get(Series, series_a).library_id
    db.close()

    by_letter = {row["letter"]: row for row in client.get(f"/series/letters?library_id={library_id}").json()}
    assert set(by_letter.keys()) == {"A"}
