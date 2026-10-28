"""Reading pages (kodex.reading.pages): as stored, or narrowed and trimmed
to WebP, cached, with ETags."""

from __future__ import annotations

import zipfile

import pytest
import pyvips

from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library


def _jpeg(width: int, height: int, *, margin: int = 0) -> bytes:
    """A dark rectangle on white, with ``margin`` white pixels around it."""
    inner = pyvips.Image.black(width - 2 * margin, height - 2 * margin, bands=3) + 40
    page = inner.embed(margin, margin, width, height, extend="white") if margin else inner
    return page.cast("uchar").jpegsave_buffer(Q=90)


@pytest.fixture
def book_id(api, tmp_path, monkeypatch):
    _, session_factory = api
    root = tmp_path / "libraries"
    (root / "serier").mkdir(parents=True)
    with zipfile.ZipFile(root / "serier" / "a.cbz", "w") as archive:
        archive.writestr("001.jpg", _jpeg(1600, 2400))
        archive.writestr("002.jpg", _jpeg(1000, 1500, margin=150))
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "libraries_root", root)
    monkeypatch.setattr(get_settings(), "covers_dir", tmp_path / "covers")
    with session_factory() as db:
        library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
        db.add(library)
        db.flush()
        book = Book(library_id=library.id, file_path="a.cbz", file_format=BookFormat.CBZ, file_size=1,
                    file_mtime=0.0, page_count=2, content_id="c" * 64)  # fmt: skip
        db.add(book)
        db.commit()
        return book.id


def _size(data: bytes) -> tuple[int, int]:
    image = pyvips.Image.new_from_buffer(data, "")
    return image.width, image.height


def test_a_page_as_stored(api, book_id):
    client, _ = api
    response = client.get(f"/api/books/{book_id}/pages/0")
    assert response.headers["content-type"] == "image/jpeg"
    assert _size(response.content) == (1600, 2400)
    again = client.get(f"/api/books/{book_id}/pages/0", headers={"if-none-match": response.headers["etag"]})
    assert again.status_code == 304


def test_a_narrower_page_is_webp_at_a_width_step(api, book_id, tmp_path):
    client, _ = api
    response = client.get(f"/api/books/{book_id}/pages/0", params={"max_width": 1000})
    assert response.headers["content-type"] == "image/webp"
    assert _size(response.content) == (1080, 1620)
    assert list((tmp_path / "covers" / "pages" / str(book_id)).rglob("*.webp"))
    assert client.get(f"/api/books/{book_id}/pages/0", params={"max_width": 1000}).content == response.content


def test_trimming_cuts_blank_margins(api, book_id):
    client, _ = api
    response = client.get(f"/api/books/{book_id}/pages/1", params={"trim": True})
    width, height = _size(response.content)
    assert abs(width - 700) <= 4 and abs(height - 1200) <= 4


def test_pages_out_of_range_are_not_found(api, book_id):
    client, _ = api
    assert client.get(f"/api/books/{book_id}/pages/9").status_code == 404
