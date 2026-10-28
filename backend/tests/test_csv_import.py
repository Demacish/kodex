"""Tests for kodex/collections/csv_import.py — C14's LOCG/Goodreads pull-list
import (parse -> fuzzy-match -> bucket). API-level preview/confirm tests
live in test_csv_import_routes.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.models.series import Series
from kodex.collections.csv_import import CsvImportError, match_rows, parse_csv
from tests.db import fresh_engine


@pytest.fixture
def db():
    engine = fresh_engine()
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()


def _make_series_with_books(db, *, title: str = "Absolute Corvid", issues: list[int] = (1, 2, 3)) -> Series:
    library = Library(name="Serier", path=f"lib-{title}", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    series = Series(library_id=library.id, title=title, sort_title=title, path=title)
    db.add(series)
    db.flush()
    for n in issues:
        db.add(
            Book(
                library_id=library.id,
                series_id=series.id,
                file_path=f"{title}/{n}.cbz",
                file_format=BookFormat.CBZ,
                file_size=1,
                file_mtime=0.0,
                number=float(n),
            )
        )
    db.commit()
    return series


def test_parse_csv_finds_title_column_case_insensitively():
    content = b"Series,Issue\nAbsolute Corvid,1\n"
    rows = parse_csv(content)
    assert rows == [{"title": "Absolute Corvid", "author": None, "issue_number": "1"}]


def test_parse_csv_goodreads_style_headers():
    content = b'Title,Author,ISBN13\n"Saga, Vol. 1",Brian K. Vaughan,9781607066019\n'
    rows = parse_csv(content)
    assert rows[0]["title"] == "Saga, Vol. 1"
    assert rows[0]["author"] == "Brian K. Vaughan"
    assert rows[0]["issue_number"] is None


def test_parse_csv_skips_blank_title_rows():
    content = b"Title\nReal Book\n\n"
    rows = parse_csv(content)
    assert len(rows) == 1


def test_parse_csv_raises_when_no_title_column():
    with pytest.raises(CsvImportError):
        parse_csv(b"Foo,Bar\n1,2\n")


def test_parse_csv_raises_when_no_header_at_all():
    with pytest.raises(CsvImportError):
        parse_csv(b"")


def test_match_rows_exact_title_is_auto_matched(db):
    _make_series_with_books(db)
    rows = [{"title": "Absolute Corvid", "author": None, "issue_number": None}]

    result = match_rows(db, rows)

    assert result[0].bucket == "matched"
    assert result[0].matched_series_title == "Absolute Corvid"
    assert len(result[0].book_ids) == 3  # whole series, no issue number given


def test_match_rows_with_issue_number_narrows_to_one_book(db):
    series = _make_series_with_books(db)
    rows = [{"title": "Absolute Corvid", "author": None, "issue_number": "2"}]

    result = match_rows(db, rows)

    matched_book = db.query(Book).filter(Book.series_id == series.id, Book.number == 2.0).one()
    assert result[0].book_ids == [matched_book.id]


def test_match_rows_unmatched_title_gets_empty_book_ids(db):
    _make_series_with_books(db)
    rows = [{"title": "Completely Unrelated Nonexistent Thing", "author": None, "issue_number": None}]

    result = match_rows(db, rows)

    assert result[0].bucket == "unmatched"
    assert result[0].book_ids == []
    assert result[0].matched_series_id is None


def test_match_rows_empty_library_everything_unmatched(db):
    rows = [{"title": "Anything", "author": None, "issue_number": None}]
    result = match_rows(db, rows)
    assert result[0].bucket == "unmatched"
