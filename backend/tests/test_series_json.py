"""Tests for app/scanning/series_json.py — B9's self-describing-library
export/import (see that module's own docstring for the full recovery
story this exists for).
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.models.metadata import BookMetadata
from app.models.series import Series
from app.scanning.series_json import (
    SERIES_JSON_FILENAME,
    export_series,
    import_library_series_json,
    import_series_json_file,
)
from tests.db import fresh_engine


@pytest.fixture
def db():
    engine = fresh_engine()
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()


def _make_series_with_books(
    db, *, folder: str = "Absolute Corvid", library_path: str = "serier", library: Library | None = None
) -> tuple[Library, Series]:
    if library is None:
        library = Library(name="Serier", path=library_path, library_type=LibraryType.COMICS)
        db.add(library)
        db.flush()
    series = Series(
        library_id=library.id,
        title="Absolute Corvid",
        sort_title="Absolute Corvid",
        path=folder,
        comicvine_volume_id=111,
    )
    db.add(series)
    db.flush()
    for n in (1, 2):
        book = Book(
            library_id=library.id,
            series_id=series.id,
            file_path=f"{folder}/{n:03d}.cbz",
            file_format=BookFormat.CBZ,
            file_size=1,
            file_mtime=0.0,
            number=float(n),
        )
        db.add(book)
        db.flush()
        db.add(
            BookMetadata(
                book_id=book.id,
                title=f"Absolute Corvid #{n}",
                sort_title=f"Absolute Corvid #{n}",
                authors=["Writer"],
                genres=["Superhero"],
                external_ids={"comicvine_issue_id": 1000 + n},
            )
        )
    db.commit()
    return library, series


def test_export_series_writes_file_with_expected_shape(db, tmp_path):
    library, series = _make_series_with_books(db)

    path = export_series(series, libraries_root=tmp_path)

    assert path == tmp_path / "serier" / "Absolute Corvid" / SERIES_JSON_FILENAME
    data = json.loads(path.read_text())
    assert data["series"]["title"] == "Absolute Corvid"
    assert data["series"]["comicvine_volume_id"] == 111
    assert len(data["books"]) == 2
    first = next(b for b in data["books"] if b["file_path"].endswith("001.cbz"))
    assert first["number"] == 1.0
    assert first["metadata"]["authors"] == ["Writer"]
    assert first["metadata"]["external_ids"] == {"comicvine_issue_id": 1001}


def test_export_series_returns_none_when_no_books(db, tmp_path):
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    series = Series(library_id=library.id, title="Empty", sort_title="Empty", path="Empty")
    db.add(series)
    db.commit()

    assert export_series(series, libraries_root=tmp_path) is None


def test_export_series_returns_none_when_books_span_multiple_folders(db, tmp_path):
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    series = Series(library_id=library.id, title="Weird", sort_title="Weird", path="Weird")
    db.add(series)
    db.flush()
    db.add(
        Book(
            library_id=library.id,
            series_id=series.id,
            file_path="FolderA/1.cbz",
            file_format=BookFormat.CBZ,
            file_size=1,
            file_mtime=0.0,
        )
    )
    db.add(
        Book(
            library_id=library.id,
            series_id=series.id,
            file_path="FolderB/1.cbz",
            file_format=BookFormat.CBZ,
            file_size=1,
            file_mtime=0.0,
        )
    )
    db.commit()

    assert export_series(series, libraries_root=tmp_path) is None


def test_import_restores_metadata_onto_matching_book(db, tmp_path):
    library, series = _make_series_with_books(db)
    path = export_series(series, libraries_root=tmp_path)

    # Simulate a DB wipe: blow away the metadata (as if only bare Book
    # rows survived a rescan) but keep the Book/file_path rows themselves.
    for book in series.books:
        book.book_metadata.authors = []
        book.book_metadata.genres = []
        db.add(book.book_metadata)
    db.commit()

    result = import_series_json_file(db, library, path)

    assert result["updated"] == 2
    assert result["not_found"] == 0
    db.expire_all()
    restored = db.query(Book).filter(Book.file_path == "Absolute Corvid/001.cbz").one()
    assert restored.book_metadata.authors == ["Writer"]
    assert restored.book_metadata.genres == ["Superhero"]


def test_import_counts_not_found_for_missing_book(db, tmp_path):
    library, series = _make_series_with_books(db)
    path = export_series(series, libraries_root=tmp_path)

    # Delete one of the two books the export referenced (e.g. the file was
    # removed from disk and a rescan dropped its row).
    book_to_delete = next(b for b in series.books if b.file_path.endswith("002.cbz"))
    db.delete(book_to_delete)
    db.commit()

    result = import_series_json_file(db, library, path)

    assert result["updated"] == 1
    assert result["not_found"] == 1


def test_import_creates_metadata_row_when_book_has_none(db, tmp_path):
    library, series = _make_series_with_books(db)
    path = export_series(series, libraries_root=tmp_path)

    book = next(b for b in series.books if b.file_path.endswith("001.cbz"))
    db.delete(book.book_metadata)
    book.book_metadata = None
    db.add(book)
    db.commit()

    result = import_series_json_file(db, library, path)
    assert result["updated"] == 2

    db.expire_all()
    restored = db.query(Book).filter(Book.file_path == "Absolute Corvid/001.cbz").one()
    assert restored.book_metadata is not None
    assert restored.book_metadata.authors == ["Writer"]


def test_import_library_series_json_walks_nested_folders(db, tmp_path):
    library, series_a = _make_series_with_books(db, folder="Series A")
    _, series_b = _make_series_with_books(db, folder="Series B", library=library)

    export_series(series_a, libraries_root=tmp_path)
    export_series(series_b, libraries_root=tmp_path)

    results = import_library_series_json(db, library, libraries_root=tmp_path)

    assert len(results) == 2
    assert {r["updated"] for r in results} == {2}


def test_import_series_json_file_handles_malformed_json_gracefully(db, tmp_path):
    library, _series = _make_series_with_books(db)
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("not valid json{{{")

    result = import_series_json_file(db, library, bad_path)

    assert result["updated"] == 0
    assert "error" in result
