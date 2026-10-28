"""The scanner's passes (app/scanning/scanner.py): files read in a process
pool, a bad file losing only itself, and unchanged files never read."""

from __future__ import annotations

import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.book import Book
from app.models.enums import LibraryType
from app.models.library import Library


def _cbz(path: Path, salt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for i in range(2):
            zf.writestr(f"{i:03d}.jpg", f"page {i} of {salt}".encode())


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


def test_many_files_are_read_in_a_process_pool(db_session, library):
    from app.scanning.scanner import scan_library

    library, root = library
    for n in range(1, 41):
        _cbz(root / "Harbour Lights (2019)" / f"Harbour Lights {n:03d} (2019).cbz", f"h{n}")
    stats = scan_library(db_session, library, workers=2)
    assert (stats.books_added, stats.errors) == (40, [])
    books = db_session.query(Book).all()
    assert all(b.content_id and b.content_hash and b.page_count == 2 for b in books)
    assert len({b.series_id for b in books}) == 1


def test_a_bad_file_loses_only_itself(db_session, library, monkeypatch):
    import app.scanning.scanner as scanner

    library, root = library
    for name in ("Quiet Coast 001.cbz", "Quiet Coast 002.cbz", "Quiet Coast 003.cbz"):
        _cbz(root / "Quiet Coast" / name, name)
    original = scanner._apply

    def failing(db, library, facts, *args):
        if facts.relative_path.endswith("002.cbz"):
            raise RuntimeError("simulated failure")
        return original(db, library, facts, *args)

    monkeypatch.setattr(scanner, "_apply", failing)
    stats = scanner.scan_library(db_session, library, workers=1)
    assert stats.books_added == 2 and len(stats.errors) == 1
    assert sorted(Path(b.file_path).name for b in db_session.query(Book)) == [
        "Quiet Coast 001.cbz",
        "Quiet Coast 003.cbz",
    ]


def test_a_rescan_reads_no_unchanged_file(db_session, library, monkeypatch):
    import app.scanning.scanner as scanner

    library, root = library
    _cbz(root / "Lantern Keep" / "Lantern Keep 001.cbz", "k1")
    scanner.scan_library(db_session, library, workers=1)
    read: list[str] = []
    original = scanner.inspect_file
    monkeypatch.setattr(scanner, "inspect_file", lambda *a, **k: (read.append(a[1]), original(*a, **k))[1])
    stats = scanner.scan_library(db_session, library, workers=1)
    assert (stats.books_unchanged, read) == (1, [])
