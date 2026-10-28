"""Tests for GET /books/{id}/cover — the WebP-thumbnail-cache + real
conditional-GET (ETag/If-None-Match) upgrade. See
app/api/routes/books.py's get_cover/_get_or_create_thumbnail/_stat_etag.
"""

from __future__ import annotations

import io

from PIL import Image

from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.models.metadata import BookMetadata


def _seed_book_with_cover(session_factory, covers_dir) -> int:
    db = session_factory()
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    book = Book(library_id=library.id, file_path="A/1.cbz", file_format=BookFormat.CBZ, file_size=1, file_mtime=0.0)
    db.add(book)
    db.flush()

    covers_dir.mkdir(parents=True, exist_ok=True)
    cover_path = covers_dir / f"{book.id}.jpg"
    buffer = io.BytesIO()
    Image.new("RGB", (800, 1200), color=(120, 40, 200)).save(buffer, format="JPEG")
    cover_path.write_bytes(buffer.getvalue())

    book.book_metadata = BookMetadata(book_id=book.id, title="A #1", sort_title="A #1", cover_path=cover_path.name)
    db.add(book.book_metadata)
    db.commit()
    book_id = book.id
    db.close()
    return book_id


def _patch_covers_dir(monkeypatch, tmp_path):
    import app.api.routes.books as books_module
    from app.config import Settings

    monkeypatch.setattr(books_module, "get_settings", lambda: Settings(covers_dir=tmp_path))


def test_thumbnail_is_served_as_webp_with_etag(api, tmp_path, monkeypatch):
    _patch_covers_dir(monkeypatch, tmp_path)
    client, session_factory = api
    book_id = _seed_book_with_cover(session_factory, tmp_path)

    response = client.get(f"/books/{book_id}/cover", params={"thumb": "true"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert response.headers.get("etag")
    # Actually re-encoded, not just the original JPEG bytes handed back.
    assert Image.open(io.BytesIO(response.content)).format == "WEBP"

    from kodex.library.covers import cover_file

    assert cover_file(tmp_path, book_id, "medium").is_file()  # thumb=true is the generated medium size


def test_cover_conditional_get_returns_304_on_matching_etag(api, tmp_path, monkeypatch):
    _patch_covers_dir(monkeypatch, tmp_path)
    client, session_factory = api
    book_id = _seed_book_with_cover(session_factory, tmp_path)

    first = client.get(f"/books/{book_id}/cover")
    assert first.status_code == 200
    etag = first.headers["etag"]
    assert etag

    second = client.get(f"/books/{book_id}/cover", headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.content == b""
    assert second.headers["etag"] == etag


def test_cover_conditional_get_thumb_returns_304_on_matching_etag(api, tmp_path, monkeypatch):
    _patch_covers_dir(monkeypatch, tmp_path)
    client, session_factory = api
    book_id = _seed_book_with_cover(session_factory, tmp_path)

    first = client.get(f"/books/{book_id}/cover", params={"thumb": "true"})
    etag = first.headers["etag"]

    second = client.get(f"/books/{book_id}/cover", params={"thumb": "true"}, headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.content == b""


def test_cover_stale_etag_still_returns_full_body(api, tmp_path, monkeypatch):
    _patch_covers_dir(monkeypatch, tmp_path)
    client, session_factory = api
    book_id = _seed_book_with_cover(session_factory, tmp_path)

    response = client.get(f"/books/{book_id}/cover", headers={"If-None-Match": '"stale-etag"'})
    assert response.status_code == 200
    assert response.content
