"""Per-page pixel sizes (app/scanning/dimensions.py, GET
/books/{id}/pages/dimensions)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

import app.api.routes.books as books_routes
import app.scanning.dimensions as dimensions
from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.scanning.dimensions import cbr_page_dimensions, cheap_page_dimensions


def _png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height)).save(buffer, format="PNG")
    return buffer.getvalue()


def _cbz(path: Path, sizes: list[tuple[int, int]]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for index, (w, h) in enumerate(sizes):
            zf.writestr(f"{index:03}.png", _png(w, h))
        zf.writestr("ComicInfo.xml", "<ComicInfo/>")
    return path


def test_cbz_sizes_in_page_order_including_a_spread(tmp_path):
    path = _cbz(tmp_path / "a.cbz", [(60, 90), (120, 90), (60, 90)])
    assert cheap_page_dimensions(path, BookFormat.CBZ) == [[60, 90], [120, 90], [60, 90]]


def test_unreadable_page_is_none_not_an_error(tmp_path):
    path = tmp_path / "b.cbz"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("001.png", _png(10, 20))
        zf.writestr("002.png", b"not an image")
    assert cheap_page_dimensions(path, BookFormat.CBZ) == [[10, 20], None]


def test_image_folder_sizes(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "002.png").write_bytes(_png(30, 40))
    (folder / "001.png").write_bytes(_png(10, 20))
    assert cheap_page_dimensions(folder, BookFormat.IMAGE_FOLDER) == [[10, 20], [30, 40]]


def test_cbr_sizes_come_from_the_extracted_page_cache(tmp_path, monkeypatch):
    pages = [tmp_path / "p0.png", tmp_path / "p1.png"]
    pages[0].write_bytes(_png(50, 70))
    pages[1].write_bytes(_png(100, 70))
    monkeypatch.setattr(dimensions.archive, "extract_page", lambda path, fmt, index, cache: pages[index])
    assert cbr_page_dimensions(tmp_path / "x.cbr", 2, tmp_path / "cache") == [[50, 70], [100, 70]]


def test_endpoint_backfills_cbz_and_queues_cbr(api, tmp_path, monkeypatch):
    client, session_factory = api
    root = tmp_path / "libraries"
    (root / "serier").mkdir(parents=True)
    _cbz(root / "serier" / "a.cbz", [(60, 90), (120, 90)])
    monkeypatch.setattr(books_routes, "get_settings", lambda: SimpleNamespace(libraries_root=root))
    queued = []
    monkeypatch.setattr(
        books_routes, "get_panel_queue", lambda: SimpleNamespace(enqueue=lambda *a, **k: queued.append((a, k)))
    )

    db = session_factory()
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    cbz = Book(
        library_id=library.id, file_path="a.cbz", file_format=BookFormat.CBZ, file_size=1, file_mtime=0.0, page_count=2
    )
    cbr = Book(
        library_id=library.id, file_path="b.cbr", file_format=BookFormat.CBR, file_size=1, file_mtime=0.0, page_count=2
    )
    epub = Book(library_id=library.id, file_path="c.epub", file_format=BookFormat.EPUB, file_size=1, file_mtime=0.0)
    db.add_all([cbz, cbr, epub])
    db.commit()
    ids = (cbz.id, cbr.id, epub.id)
    db.close()

    assert client.get(f"/books/{ids[0]}/pages/dimensions").json() == {
        "dimensions": [[60, 90], [120, 90]],
        "pending": False,
    }
    db = session_factory()
    assert db.get(Book, ids[0]).page_dimensions == [[60, 90], [120, 90]]  # stored for next time
    db.close()

    assert client.get(f"/books/{ids[1]}/pages/dimensions").json() == {"dimensions": None, "pending": True}
    assert queued[0][1]["job_id"] == f"page-dimensions-{ids[1]}"

    assert client.get(f"/books/{ids[2]}/pages/dimensions").status_code == 400
