"""kodex.library.covers: three cover sizes from each kind of source, made
once per source, and GET /books/{id}/cover?size=."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.models.book import Book
from app.models.enums import BookFormat, LibraryType, MetadataSource
from app.models.library import Library
from app.models.metadata import BookMetadata
from kodex.library import covers
from tests.pdf_helpers import write_text_pdf


def _jpeg(size=(1200, 1800), colour=(200, 60, 40)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "JPEG")
    return out.getvalue()


def _epub(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", '<?xml version="1.0"?><container version="1.0" '
                    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                    '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                    "</rootfiles></container>")  # fmt: skip
        zf.writestr("OEBPS/content.opf", '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata/>'
                    '<manifest><item id="c" href="images/cover%20art.jpg" media-type="image/jpeg" '
                    'properties="cover-image"/></manifest></package>')  # fmt: skip
        zf.writestr("OEBPS/images/cover art.jpg", _jpeg((600, 900)))
    return path


@pytest.fixture
def setup(tmp_path, db_session):
    root, covers_dir = tmp_path / "libraries", tmp_path / "covers"
    (root / "lib").mkdir(parents=True)
    library = Library(name="Lib", path="lib", library_type=LibraryType.MIXED)
    db_session.add(library)
    db_session.commit()

    def book(name: str, file_format: BookFormat) -> Book:
        b = Book(library_id=library.id, file_path=name, file_format=file_format, content_id=f"id-{name}",
                 file_size=1, file_mtime=0.0)  # fmt: skip
        b.book_metadata = BookMetadata(title=name, sort_title=name, source=MetadataSource.EMBEDDED)
        db_session.add(b)
        db_session.commit()
        return b

    return SimpleNamespace(root=root, covers=covers_dir, lib=root / "lib", book=book, db=db_session)


def _edges(path: Path) -> int:
    with Image.open(path) as image:
        return max(image.size)


def test_three_sizes_from_an_archive_page(setup):
    with zipfile.ZipFile(setup.lib / "a.cbz", "w") as zf:
        zf.writestr("001.jpg", _jpeg())
        zf.writestr("002.jpg", _jpeg(colour=(0, 0, 0)))
    book = setup.book("a.cbz", BookFormat.CBZ)
    assert covers.make(book, setup.root, setup.covers)
    assert [_edges(covers.cover_file(setup.covers, book.id, s)) for s in covers.SIZES] == [200, 400, 1000]
    assert book.cover_key
    assert not covers.make(book, setup.root, setup.covers)  # same source: nothing to do


def test_epub_and_pdf_covers(setup):
    _epub(setup.lib / "b.epub")
    write_text_pdf(setup.lib / "c.pdf", ["Harbour Lights"])
    for name, fmt in (("b.epub", BookFormat.EPUB), ("c.pdf", BookFormat.PDF)):
        book = setup.book(name, fmt)
        assert covers.make(book, setup.root, setup.covers), name
        with Image.open(covers.cover_file(setup.covers, book.id, "large")) as image:
            assert image.format == "WEBP"


def test_a_downloaded_cover_wins(setup):
    with zipfile.ZipFile(setup.lib / "d.cbz", "w") as zf:
        zf.writestr("001.jpg", _jpeg())
    book = setup.book("d.cbz", BookFormat.CBZ)
    covers.make(book, setup.root, setup.covers)
    first = book.cover_key
    (setup.covers / "dl").mkdir(parents=True)
    (setup.covers / "dl" / "d.jpg").write_bytes(_jpeg((300, 450), colour=(10, 200, 10)))
    book.book_metadata.cover_path = "dl/d.jpg"
    assert covers.make(book, setup.root, setup.covers) and book.cover_key != first
    assert _edges(covers.cover_file(setup.covers, book.id, "large")) == 450  # never enlarged


def test_cover_route_serves_sizes(api, setup, monkeypatch):
    client, _ = api
    with zipfile.ZipFile(setup.lib / "e.cbz", "w") as zf:
        zf.writestr("001.jpg", _jpeg())
    book = setup.book("e.cbz", BookFormat.CBZ)
    settings = SimpleNamespace(libraries_root=setup.root, covers_dir=setup.covers)
    monkeypatch.setattr("app.api.routes.books.get_settings", lambda: settings)
    response = client.get(f"/books/{book.id}/cover?size=small")
    assert response.status_code == 200 and response.headers["content-type"] == "image/webp"
    with Image.open(io.BytesIO(response.content)) as image:
        assert max(image.size) == 200
    again = client.get(f"/books/{book.id}/cover?size=small", headers={"If-None-Match": response.headers["etag"]})
    assert again.status_code == 304
    assert client.get(f"/books/{book.id}/cover?size=huge").status_code == 422
