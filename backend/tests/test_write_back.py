"""Writing metadata back into files (kodex.library.write_back), duplicates
(kodex.library.duplicates) and the phase 2 gate: after write-back a book
keeps its id, its KOReader ids and its duplicates."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.models.series import Series
from app.progress.sync import books_for_document
from kodex.formats.comicinfo import build_comicinfo_xml, parse_comicinfo_xml
from kodex.formats.identity import content_id
from kodex.library import duplicates
from kodex.library.write_back import WriteBackRefused, convert_to_cbz, write_back_library, write_comicinfo

_PAGES = {f"{i:03d}.jpg": bytes([i]) * 30000 for i in range(1, 4)}
_ORIGINAL_COMICINFO = (
    b'<?xml version="1.0"?><ComicInfo><Series>Old Name</Series><ScanInformation>scanned</ScanInformation>'
    b'<Pages><Page Image="0" Type="FrontCover"/></Pages></ComicInfo>'
)


def _cbz(path: Path, comicinfo: bytes | None = None) -> Path:
    """ComicInfo first, as many tagging tools write it: a rewrite then moves
    every page, so the file's KOReader id changes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        if comicinfo:
            zf.writestr("ComicInfo.xml", comicinfo)
        for name, data in _PAGES.items():
            zf.writestr(name, data)
    return path


def test_comicinfo_is_merged_into_the_existing_one():
    merged = build_comicinfo_xml({"Series": "Harbour Lights", "Number": "1", "ScanInformation": None},
                                 _ORIGINAL_COMICINFO)  # fmt: skip
    parsed = parse_comicinfo_xml(merged)
    assert (parsed["series"], parsed["number"]) == ("Harbour Lights", "1")
    assert "scan_information" not in parsed
    assert b'Type="FrontCover"' in merged  # the page list Kodex doesn't manage is kept
    assert merged.index(b"<Series>") < merged.index(b"<Number>") < merged.index(b"<Pages>")


@pytest.fixture
def env(tmp_path, monkeypatch, db_session):
    import app.scanning.scanner as scanner

    root = tmp_path / "libraries"
    (root / "serier").mkdir(parents=True)
    monkeypatch.setattr(scanner, "get_settings", lambda: SimpleNamespace(libraries_root=root, sorting_auto_apply=False))
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS, write_back=True)
    db_session.add(library)
    db_session.commit()

    def scan():
        stats = scanner.scan_library(db_session, library, workers=1)
        db_session.commit()
        db_session.expire_all()
        return stats

    return SimpleNamespace(root=root, lib=root / "serier", library=library, scan=scan, db=db_session)


def test_write_back_keeps_the_book_its_koreader_ids_and_its_duplicates(env):
    """The phase 2 gate."""
    first = _cbz(env.lib / "Harbour Lights (2019)" / "Harbour Lights 001 (2019).cbz", _ORIGINAL_COMICINFO)
    _cbz(env.lib / "Copies" / "Harbour Lights 001 (2019).cbz", _ORIGINAL_COMICINFO)
    env.scan()
    book = env.db.query(Book).filter(Book.file_path.like("Harbour Lights (2019)%")).one()
    copy = env.db.query(Book).filter(Book.file_path.like("Copies%")).one()
    assert copy.duplicate_of_id == book.id
    old_id, identity, pages = book.content_hash, book.content_id, set(_PAGES)

    assert write_comicinfo(env.db, book, env.root)
    env.db.commit()
    assert not write_comicinfo(env.db, book, env.root)  # nothing new to write
    with zipfile.ZipFile(first) as zf:
        assert pages <= set(zf.namelist())
        written = parse_comicinfo_xml(zf.read("ComicInfo.xml"))
    assert written["series"] == book.series.title and written["number"] == "1"
    assert content_id(first, BookFormat.CBZ) == identity

    stats = env.scan()
    assert stats.books_unchanged == 2 and stats.books_updated == 0  # the rewrite was recorded, not rediscovered
    book, copy = env.db.get(Book, book.id), env.db.get(Book, copy.id)
    assert (book.content_id, copy.duplicate_of_id) == (identity, book.id)
    assert book.content_hash != old_id
    for document in (old_id, book.content_hash):
        assert book.id in [b.id for b in books_for_document(env.db, document)]


def test_comic_vine_ids_go_where_other_tools_look(env):
    _cbz(env.lib / "Quiet Coast" / "Quiet Coast 002.cbz")
    env.scan()
    book = env.db.query(Book).one()
    book.book_metadata.external_ids = {"comicvine_issue_id": 290425}
    write_comicinfo(env.db, book, env.root)
    with zipfile.ZipFile(env.lib / "Quiet Coast" / "Quiet Coast 002.cbz") as zf:
        parsed = parse_comicinfo_xml(zf.read("ComicInfo.xml"))
    assert "4000-290425" in parsed["web"] and "[Issue ID 290425]" in parsed["notes"]


def test_nothing_is_written_without_write_back_or_into_a_read_only_library(env):
    path = _cbz(env.lib / "Lantern Keep" / "Lantern Keep 001.cbz")
    env.scan()
    book = env.db.query(Book).one()
    before = path.read_bytes()
    env.library.write_back = False
    with pytest.raises(WriteBackRefused):
        write_comicinfo(env.db, book, env.root)
    env.library.write_back, env.library.read_only = True, True
    with pytest.raises(WriteBackRefused):
        write_back_library(env.db, env.library, env.root)
    assert path.read_bytes() == before


def test_write_back_library_writes_series_json(env):
    _cbz(env.lib / "Driftwood (2021)" / "Driftwood 001 (2021).cbz")
    _cbz(env.lib / "Driftwood (2021)" / "Driftwood 002 (2021).cbz")
    env.scan()
    result = write_back_library(env.db, env.library, env.root)
    assert result["comicinfo_written"] == 2 and result["series_json"] >= 1
    data = json.loads((env.lib / "Driftwood (2021)" / "series.json").read_text())
    assert data["version"] == "1.0.2" and data["metadata"]["name"] == env.db.query(Series).one().title
    assert data["kodex_series_json_version"] == 1 and len(data["books"]) == 2


def test_a_converted_book_keeps_its_id_and_the_original_shows_as_a_duplicate(env):
    import py7zr

    original = env.lib / "Gulls" / "Gulls 003.cb7"
    original.parent.mkdir(parents=True)
    with py7zr.SevenZipFile(original, "w") as z:
        for name, data in _PAGES.items():
            z.writestr(data, name)
    env.scan()
    book = env.db.query(Book).one()
    target = convert_to_cbz(env.db, book, env.root)
    env.db.commit()
    assert original.exists() and target.exists()
    env.scan()
    converted = env.db.get(Book, book.id)
    assert (converted.file_format, converted.file_path) == (BookFormat.CBZ, "Gulls/Gulls 003.cbz")
    leftover = env.db.query(Book).filter(Book.id != book.id).one()
    assert leftover.file_format == BookFormat.CB7 and leftover.duplicate_of_id == book.id


def test_a_mark_goes_away_with_the_copy(env):
    _cbz(env.lib / "A" / "Harbour Watch 001.cbz")
    copy = _cbz(env.lib / "B" / "Harbour Watch 001.cbz")
    env.scan()
    assert len(duplicates.exact_groups(env.db)) == 1
    copy.unlink()
    env.scan()
    assert duplicates.exact_groups(env.db) == []


def test_similar_books_are_found_by_their_covers(env):
    a = _cbz(env.lib / "S" / "Harbour Watch 004.cbz")
    with zipfile.ZipFile(env.lib / "S" / "Harbour Watch 004 (other release).cbz", "w") as zf:
        for name, data in _PAGES.items():
            zf.writestr(name, data + b"x")  # other bytes, so another content id
    env.scan()
    books = env.db.query(Book).order_by(Book.id).all()
    assert a.exists() and len(books) == 2 and books[0].content_id != books[1].content_id
    for book, phash in zip(books, ("ffff0000ffff0000", "ffff0000ffff0001"), strict=True):
        book.cover_phash = phash
        book.number_label = "4"
    books[1].series_id = books[0].series_id
    env.db.commit()
    assert duplicates.similar_groups(env.db) == [[books[0].id, books[1].id]]
    books[1].cover_phash = "0000ffff0000ffff"
    env.db.commit()
    assert duplicates.similar_groups(env.db) == []


def test_write_back_and_convert_api(api, env, monkeypatch):
    client, _ = api
    _cbz(env.lib / "Gulls" / "Gulls 001.cbz")
    env.scan()
    book = env.db.query(Book).one()
    monkeypatch.setattr("app.workers.queue.get_scan_queue", lambda: SimpleNamespace(
        enqueue=lambda *a, **k: SimpleNamespace(id="7")))  # fmt: skip
    assert client.post(f"/library/libraries/{env.library.id}/write-back").json() == {"job_id": "7"}
    assert client.post(f"/library/books/{book.id}/convert").status_code == 409  # already a CBZ
    env.library.write_back = False
    env.db.commit()
    assert client.post(f"/library/libraries/{env.library.id}/write-back").status_code == 409
    assert client.get("/library/duplicates").json() == {"exact": [], "similar": []}
