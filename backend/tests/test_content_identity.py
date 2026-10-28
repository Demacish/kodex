"""kodex.formats.identity's content id, and the scanner keeping a book's
identity through metadata written into the file, conversion and moves."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.progress.sync import books_for_document
from kodex.formats.identity import content_id, koreader_partial_md5
from kodex.library.models import BookFileHash

_PAGES = {f"{i:03d}.jpg": bytes([i]) * (2000 + i) for i in range(1, 4)}


def _cbz(path: Path, pages=_PAGES, comicinfo: str | None = None, compression=zipfile.ZIP_STORED) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=compression) as zf:
        for name, data in pages.items():
            zf.writestr(name, data)
        if comicinfo:
            zf.writestr("ComicInfo.xml", comicinfo)
    return path


def test_metadata_and_repacking_dont_change_the_content_id(tmp_path):
    plain = content_id(_cbz(tmp_path / "a.cbz"), BookFormat.CBZ)
    tagged = _cbz(tmp_path / "b.cbz", comicinfo="<ComicInfo><Series>Harbour Lights</Series></ComicInfo>",
                  compression=zipfile.ZIP_DEFLATED)  # fmt: skip
    assert content_id(tagged, BookFormat.CBZ) == plain
    assert koreader_partial_md5(tagged) != koreader_partial_md5(tmp_path / "a.cbz")
    other = _cbz(tmp_path / "c.cbz", pages={**_PAGES, "004.jpg": b"new page"})
    assert content_id(other, BookFormat.CBZ) != plain


def test_a_converted_archive_keeps_its_content_id(tmp_path):
    import py7zr

    seven = tmp_path / "a.cb7"
    with py7zr.SevenZipFile(seven, "w") as z:
        for name, data in _PAGES.items():
            z.writestr(data, name)
    assert content_id(seven, BookFormat.CB7) == content_id(_cbz(tmp_path / "a.cbz"), BookFormat.CBZ)


def test_an_epubs_metadata_doesnt_change_its_content_id(tmp_path):
    def epub(path: Path, title: str) -> Path:
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip")
            zf.writestr("OEBPS/content.opf", f"<package><metadata><title>{title}</title></metadata></package>")
            zf.writestr("OEBPS/chapter1.xhtml", "<html><body>Once upon a tide.</body></html>")
        return path

    first = content_id(epub(tmp_path / "a.epub", "Harbour Lights"), BookFormat.EPUB)
    assert content_id(epub(tmp_path / "b.epub", "Harbour Lights, revised"), BookFormat.EPUB) == first


def test_a_pdf_gets_a_partial_hash(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    a.write_bytes(b"%PDF-1.7\n" + b"x" * 5000)
    b.write_bytes(b"%PDF-1.7\n" + b"y" * 5000)
    assert content_id(a, BookFormat.PDF) != content_id(b, BookFormat.PDF)
    assert len(content_id(a, BookFormat.PDF)) == 64


@pytest.fixture
def library(tmp_path, monkeypatch, db_session):
    import app.scanning.scanner as scanner

    root = tmp_path / "libraries"
    (root / "serier").mkdir(parents=True)
    monkeypatch.setattr(scanner, "get_settings", lambda: SimpleNamespace(libraries_root=root, sorting_auto_apply=False))
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db_session.add(library)
    db_session.commit()
    return library, root / "serier"


def _scan(db, library):
    import app.scanning.scanner as scanner

    stats = scanner.scan_library(db, library)
    db.commit()
    return stats


def test_writing_comicinfo_into_a_book_keeps_it_and_its_old_koreader_id(db_session, library):
    library, root = library
    path = _cbz(root / "Harbour Lights" / "Harbour Lights 001.cbz")
    _scan(db_session, library)
    book = db_session.query(Book).one()
    old_hash, identity = book.content_hash, book.content_id
    assert identity and old_hash

    # Repacked with compression, as tagging tools do (appending ComicInfo to
    # a stored zip can leave KOReader's sampled bytes, and so its id, alone).
    _cbz(path, comicinfo="<ComicInfo><Series>Harbour Lights</Series><Number>1</Number></ComicInfo>",
         compression=zipfile.ZIP_DEFLATED)  # fmt: skip
    os.utime(path, (1, 2))  # a different mtime, as a rewrite gives
    _scan(db_session, library)
    db_session.expire_all()
    book = db_session.query(Book).one()
    assert book.content_id == identity and book.content_hash != old_hash
    hashes = {h.value for h in db_session.query(BookFileHash).filter_by(book_id=book.id)}
    assert hashes == {old_hash, book.content_hash}
    # A device that downloaded the file before still syncs against the book.
    assert [b.id for b in books_for_document(db_session, old_hash)] == [book.id]


def test_a_book_converted_and_moved_is_the_same_book(db_session, library):
    import py7zr

    library, root = library
    old = root / "Harbour Lights" / "Harbour Lights 002.cb7"
    old.parent.mkdir(parents=True)
    with py7zr.SevenZipFile(old, "w") as z:
        for name, data in _PAGES.items():
            z.writestr(data, name)
    _scan(db_session, library)
    book_id = db_session.query(Book).one().id

    old.unlink()
    _cbz(root / "Harbour Lights (2019)" / "Harbour Lights 002.cbz")
    _scan(db_session, library)
    db_session.expire_all()
    book = db_session.query(Book).one()
    assert (book.id, book.file_format, book.file_path) == (
        book_id,
        BookFormat.CBZ,
        "Harbour Lights (2019)/Harbour Lights 002.cbz",
    )


def test_books_scanned_before_content_ids_get_one(db_session, library):
    library, root = library
    _cbz(root / "Harbour Lights" / "Harbour Lights 003.cbz")
    _scan(db_session, library)
    book = db_session.query(Book).one()
    expected, book.content_id = book.content_id, None
    db_session.commit()
    _scan(db_session, library)
    db_session.expire_all()
    assert db_session.query(Book).one().content_id == expected
