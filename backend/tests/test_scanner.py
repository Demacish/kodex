from __future__ import annotations

import zipfile
from pathlib import Path

from app.config import Settings
from app.models.book import Book
from app.models.enums import BookEditionType, BookFormat, LibraryType
from app.models.library import Library
from app.models.series import Series
from app.scanning import scanner

# The scanner only looks at file extensions when counting pages, never at
# image content — see conftest.py's own copy of this comment.
_TINY_PNG = b"not-a-real-png-but-the-scanner-never-decodes-it"


def _patch_libraries_root(monkeypatch, root: Path) -> None:
    stub_settings = Settings(libraries_root=root.parent, database_url="sqlite:///:memory:")
    monkeypatch.setattr(scanner, "get_settings", lambda: stub_settings)


def test_scan_library_discovers_all_formats(db_session, library_root, monkeypatch):
    _patch_libraries_root(monkeypatch, library_root)

    # v1's grouping (one series per first-level folder, nothing for files
    # in the root) is the "folder" strategy.
    library = Library(
        name="Test library", path=library_root.name, library_type=LibraryType.COMICS, grouping_strategy="folder"
    )
    db_session.add(library)
    db_session.commit()

    stats = scanner.scan_library(db_session, library)

    assert stats.errors == []
    assert stats.books_added == 4  # 2 in SeriesA, 1 image-folder in SeriesB, 1 standalone EPUB

    series = db_session.query(Series).order_by(Series.title).all()
    assert [s.title for s in series] == ["SeriesA", "SeriesB"]

    books = db_session.query(Book).order_by(Book.file_path).all()
    by_path = {b.file_path: b for b in books}

    cbz = by_path["SeriesA/Volume 01.cbz"]
    assert cbz.file_format == BookFormat.CBZ
    assert cbz.page_count == 2  # ComicInfo.xml is not an image, only the two .png entries count
    assert cbz.book_metadata.title == "SeriesA Volume 1"
    assert cbz.book_metadata.publisher == "Test Publisher"
    assert "Ada Testwriter" in cbz.book_metadata.authors
    assert cbz.number == 1.0

    cbr = by_path["SeriesA/Volume 02.cbr"]
    assert cbr.file_format == BookFormat.CBR
    assert cbr.page_count == 1
    assert cbr.book_metadata.title == "SeriesA Volume 2"

    image_folder = by_path["SeriesB/Chapter1"]
    assert image_folder.file_format == BookFormat.IMAGE_FOLDER
    assert image_folder.series.title == "SeriesB"

    standalone = by_path["Standalone Test Book.epub"]
    assert standalone.series_id is None
    assert standalone.file_format == BookFormat.EPUB
    assert standalone.book_metadata.title == "Standalone Test Book"
    assert standalone.book_metadata.authors == ["Test Author"]
    assert standalone.book_metadata.language == "sv"


def test_rescanning_is_idempotent(db_session, library_root, monkeypatch):
    _patch_libraries_root(monkeypatch, library_root)

    library = Library(name="Test library", path=library_root.name, library_type=LibraryType.COMICS)
    db_session.add(library)
    db_session.commit()

    first = scanner.scan_library(db_session, library)
    assert first.books_added == 4

    second = scanner.scan_library(db_session, library)
    assert second.books_added == 0
    assert second.books_updated == 0
    assert second.books_unchanged == 4

    assert db_session.query(Book).count() == 4


def test_scan_library_populates_story_arcs_from_comicinfo(db_session, tmp_path, monkeypatch):
    """End-to-end check that <StoryArc>/<StoryArcNumber> in a real CBZ's
    ComicInfo.xml survive the full scan pipeline (parser -> scanner ->
    BookMetadata row), not just the parser in isolation — see
    test_comicinfo_parser.py for the parser-level cases. This is the field
    that makes crossover-event smart collections possible (see
    kodex/collections/rules.py).

    Uses its own standalone library root rather than the shared
    `library_root` fixture, since that fixture's books have fixed
    ComicInfo.xml content and its book count is asserted exactly by other
    tests above.
    """
    root = tmp_path / "arc_library_root"
    (root / "EventSeries").mkdir(parents=True)

    comicinfo = """<?xml version="1.0" encoding="utf-8"?>
<ComicInfo>
  <Series>EventSeries</Series>
  <Title>EventSeries Volume 1</Title>
  <Number>1</Number>
  <StoryArc>Silent Tides, Civil War</StoryArc>
  <StoryArcNumber>3, 1</StoryArcNumber>
</ComicInfo>
"""
    with zipfile.ZipFile(root / "EventSeries" / "Volume 01.cbz", "w") as zf:
        zf.writestr("0001.png", _TINY_PNG)
        zf.writestr("ComicInfo.xml", comicinfo)

    _patch_libraries_root(monkeypatch, root)
    library = Library(name="Arc library", path=root.name, library_type=LibraryType.COMICS)
    db_session.add(library)
    db_session.commit()

    stats = scanner.scan_library(db_session, library)

    assert stats.errors == []
    assert stats.books_added == 1

    book = db_session.query(Book).filter(Book.file_path == "EventSeries/Volume 01.cbz").one()
    assert book.book_metadata.story_arcs == ["Silent Tides", "Civil War"]
    assert book.book_metadata.story_arc_numbers == {"Silent Tides": 3.0, "Civil War": 1.0}


def test_scan_falls_back_to_filename_number_and_detects_edition_type(db_session, tmp_path, monkeypatch):
    """A .cbz/.cbr with no ComicInfo.xml <Number> at all — this library's
    actual real-world case (see claude/forbattringar-serier-samlingar.md,
    "B"): a scene-release .cbr with no embedded metadata used to leave
    Book.number permanently NULL, breaking sort order and (via Comic
    Vine's issue-number lookup) even the auto-matched title. Also covers
    C: a "v0N"-style folder name is a collected edition, a plain 3-4
    digit number is a single issue.
    """
    root = tmp_path / "no_comicinfo_root"
    (root / "Absolute Corvid 004 (2025) (Webrip) (Some-Group)").mkdir(parents=True)
    (root / "Absolute Corvid v02 - Abomination (2026) (digital) (Some-Group)").mkdir(parents=True)

    with zipfile.ZipFile(
        root
        / "Absolute Corvid 004 (2025) (Webrip) (Some-Group)"
        / "Absolute Corvid 004 (2025) (Webrip) (Some-Group).cbz",
        "w",
    ) as zf:
        zf.writestr("0001.png", _TINY_PNG)

    with zipfile.ZipFile(
        root
        / "Absolute Corvid v02 - Abomination (2026) (digital) (Some-Group)"
        / "Absolute Corvid v02 - Abomination (2026) (digital) (Some-Group).cbz",
        "w",
    ) as zf:
        zf.writestr("0001.png", _TINY_PNG)

    _patch_libraries_root(monkeypatch, root)
    library = Library(name="No-ComicInfo library", path=root.name, library_type=LibraryType.COMICS)
    db_session.add(library)
    db_session.commit()

    stats = scanner.scan_library(db_session, library)
    assert stats.errors == []
    assert stats.books_added == 2

    issue = db_session.query(Book).filter(Book.file_path.like("Absolute Corvid 004%")).one()
    assert issue.number == 4.0
    assert issue.edition_type == BookEditionType.ISSUE

    collected = db_session.query(Book).filter(Book.file_path.like("Absolute Corvid v02%")).one()
    assert collected.number == 2.0
    assert collected.edition_type == BookEditionType.COLLECTED


def test_filename_number_fallback_only_applies_to_comics_libraries(db_session, tmp_path, monkeypatch):
    root = tmp_path / "ebook_root"
    (root / "Some Novel 004 (2025)").mkdir(parents=True)
    (root / "Some Novel 004 (2025)" / "book.epub").write_bytes(b"not-a-real-epub")

    _patch_libraries_root(monkeypatch, root)
    library = Library(name="Ebook library", path=root.name, library_type=LibraryType.EBOOKS)
    db_session.add(library)
    db_session.commit()

    stats = scanner.scan_library(db_session, library)
    assert stats.errors == []

    book = db_session.query(Book).filter(Book.file_path == "Some Novel 004 (2025)/book.epub").one()
    assert book.number is None
    assert book.edition_type == BookEditionType.ISSUE  # untouched default, not auto-detected for non-comics
