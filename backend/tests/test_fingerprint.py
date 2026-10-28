"""app/scanning/fingerprint.py — must match KOReader's util.partialMD5."""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.models.enums import BookFormat
from app.scanning.fingerprint import book_fingerprint, koreader_partial_md5


def _reference_partial_md5(data: bytes) -> str:
    """Straight transcription of KOReader's Lua loop over an in-memory
    buffer: offsets 0 (lshift(1024, -2) overflows to 0 in LuaJIT), then
    1024 << 2i for i = 0..10, 1 KiB each, stopping at the first empty read."""
    digest = hashlib.md5()
    for i in range(-1, 11):
        offset = 0 if i == -1 else 1024 << (2 * i)
        sample = data[offset : offset + 1024]
        if not sample:
            break
        digest.update(sample)
    return digest.hexdigest()


def test_partial_md5_matches_koreaders_sampling(tmp_path):
    data = bytes(range(256)) * 20000  # ~5 MB, spans several sample offsets
    path = tmp_path / "book.cbz"
    path.write_bytes(data)
    assert koreader_partial_md5(path) == _reference_partial_md5(data)


def test_small_file_hashes_only_what_exists(tmp_path):
    path = tmp_path / "tiny.epub"
    path.write_bytes(b"x" * 1500)
    # Samples at 0 and 1024 exist (the second one partial), 4096 doesn't.
    assert koreader_partial_md5(path) == hashlib.md5(b"x" * 1024 + b"x" * 476).hexdigest()


def test_image_folder_fingerprint_depends_on_names_and_sizes_only(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for folder in (a, b):
        folder.mkdir()
        (folder / "001.jpg").write_bytes(b"1234")
        (folder / "002.jpg").write_bytes(b"56")
    assert book_fingerprint(a, BookFormat.IMAGE_FOLDER) == book_fingerprint(b, BookFormat.IMAGE_FOLDER)
    (b / "002.jpg").write_bytes(b"567")
    assert book_fingerprint(a, BookFormat.IMAGE_FOLDER) != book_fingerprint(b, BookFormat.IMAGE_FOLDER)


def test_scanner_sets_and_backfills_content_hash(tmp_path, monkeypatch, db_session):
    from types import SimpleNamespace

    import app.scanning.scanner as scanner
    from app.models.book import Book
    from app.models.enums import LibraryType
    from app.models.library import Library
    from tests.conftest import _write_cbz

    root = tmp_path / "libraries"
    (root / "serier" / "SeriesA").mkdir(parents=True)
    path = root / "serier" / "SeriesA" / "SeriesA 001.cbz"
    _write_cbz(path, 1)
    monkeypatch.setattr(scanner, "get_settings", lambda: SimpleNamespace(libraries_root=root))
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db_session.add(library)
    db_session.commit()

    scanner.scan_library(db_session, library)
    book = db_session.query(Book).one()
    assert book.content_hash == koreader_partial_md5(path)

    book.content_hash = None  # as if scanned before this column existed
    db_session.commit()
    scanner.scan_library(db_session, library)
    assert db_session.query(Book).one().content_hash == koreader_partial_md5(Path(path))
