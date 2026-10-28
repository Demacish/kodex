"""API-level tests for C14's POST /collections/import-csv/preview and
POST /collections/import-csv/confirm.
"""

from __future__ import annotations

from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.models.series import Series


def _seed_series(session_factory, *, title: str = "Absolute Corvid", issues=(1, 2)) -> tuple[Library, Series]:
    db = session_factory()
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
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
    library_id, series_id = library.id, series.id
    db.close()
    return library_id, series_id


def test_preview_csv_import_buckets_rows(api):
    client, session_factory = api
    _seed_series(session_factory)

    csv_content = b"Series,Issue\nAbsolute Corvid,1\nTotally Unknown Comic,1\n"
    response = client.post(
        "/collections/import-csv/preview", files={"file": ("pull-list.csv", csv_content, "text/csv")}
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["matched"]) == 1
    assert body["matched"][0]["matched_series_title"] == "Absolute Corvid"
    assert len(body["unmatched"]) == 1


def test_preview_csv_import_rejects_missing_title_column(api):
    client, _ = api
    response = client.post(
        "/collections/import-csv/preview", files={"file": ("bad.csv", b"Foo,Bar\n1,2\n", "text/csv")}
    )
    assert response.status_code == 400


def test_confirm_csv_import_creates_manual_collection(api):
    client, session_factory = api
    _library_id, series_id = _seed_series(session_factory)
    db = session_factory()
    book_ids = [b.id for b in db.query(Book).filter(Book.series_id == series_id).all()]
    db.close()

    response = client.post("/collections/import-csv/confirm", json={"name": "Min pull-lista", "book_ids": book_ids})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Min pull-lista"
    assert body["collection_type"] == "manual"
    assert body["book_count"] == len(book_ids)


def test_confirm_csv_import_rejects_empty_book_ids(api):
    client, _ = api
    response = client.post("/collections/import-csv/confirm", json={"name": "X", "book_ids": []})
    assert response.status_code == 400


def test_confirm_csv_import_rejects_unknown_book_id(api):
    client, _ = api
    response = client.post("/collections/import-csv/confirm", json={"name": "X", "book_ids": [999999]})
    assert response.status_code == 404
