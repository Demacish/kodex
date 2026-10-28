"""kodex.formats.archive and its v1 wrapper app/scanning/archive.py: CBZ,
CBR, CB7 and image folders, recognised by content; pages in natural order;
page extraction cached by index; RAR listings reused across calls; and the
safety limits (zip-slip, decompression bombs).

CBR tests use real, prebuilt RAR archives from tests/fixtures/cbr/ (see its
README), so they exercise the actual rarfile + unar/bsdtar path rather
than a mock of it.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from app.models.enums import BookFormat
from app.scanning import archive
from kodex.formats import archive as formats

_PAGE_BYTES = b"not-a-real-image-but-extraction-never-decodes-it"
_CBR_FIXTURES = Path(__file__).parent / "fixtures" / "cbr"


@pytest.fixture(autouse=True)
def _clear_listing_cache():
    formats.clear_listing_cache()
    yield
    formats.clear_listing_cache()


def _write_cbz(path: Path, names: list[str] | int, data: bytes = _PAGE_BYTES) -> Path:
    if isinstance(names, int):
        names = [f"{i:04d}.png" for i in range(names)]
    with zipfile.ZipFile(path, "w") as zf:
        for name in names:
            zf.writestr(name, data + b" " + name.encode())
    return path


def _copy_cbr(fixture: str, dest: Path) -> Path:
    shutil.copyfile(_CBR_FIXTURES / fixture, dest)
    return dest


def _count_rar_listings(monkeypatch) -> list[Path]:
    calls: list[Path] = []
    original = formats._list_rar
    monkeypatch.setattr(formats, "_list_rar", lambda path: (calls.append(path), original(path))[1])
    return calls


def test_extract_page_cbz_skips_second_zip_read(tmp_path):
    cbz_path = _write_cbz(tmp_path / "book.cbz", 3)
    dest_dir = tmp_path / "cache"
    first = archive.extract_page(cbz_path, BookFormat.CBZ, 1, dest_dir)
    assert first.read_bytes() == _PAGE_BYTES + b" 0001.png"
    mtime_after_first = first.stat().st_mtime_ns
    second = archive.extract_page(cbz_path, BookFormat.CBZ, 1, dest_dir)
    assert second == first and second.stat().st_mtime_ns == mtime_after_first


def test_extract_page_cbr_reuses_listing_and_skips_redundant_extraction(tmp_path, monkeypatch):
    cbr_path = _copy_cbr("three_pages.rar5.cbr", tmp_path / "book.cbr")
    dest_dir = tmp_path / "cache"
    listings = _count_rar_listings(monkeypatch)
    reads: list[str] = []
    original_read = formats.RarArchive._read
    monkeypatch.setattr(
        formats.RarArchive, "_read", lambda self, entry: (reads.append(entry.name), original_read(self, entry))[1]
    )

    first = archive.extract_page(cbr_path, BookFormat.CBR, 0, dest_dir)
    assert first.read_bytes() == _PAGE_BYTES + b" 0000"
    assert len(listings) == 1 and reads == ["0000.png"]
    # The same page again: no new listing and no new decompression.
    assert archive.extract_page(cbr_path, BookFormat.CBR, 0, dest_dir) == first
    assert len(listings) == 1 and reads == ["0000.png"]
    # Another page reuses the listing but needs its own decompression.
    assert archive.extract_page(cbr_path, BookFormat.CBR, 2, dest_dir).read_bytes() == _PAGE_BYTES + b" 0002"
    assert len(listings) == 1 and reads == ["0000.png", "0002.png"]


def test_list_book_pages_cbr_uses_same_listing_as_extract_page(tmp_path, monkeypatch):
    cbr_path = _copy_cbr("three_pages.rar5.cbr", tmp_path / "book.cbr")
    listings = _count_rar_listings(monkeypatch)
    info = archive.list_book_pages(cbr_path, BookFormat.CBR)
    assert (info.page_count, info.decoder_used) == (3, "rar")
    archive.extract_page(cbr_path, BookFormat.CBR, 0, tmp_path / "cache")
    assert len(listings) == 1


def test_cbr_pages_in_a_subfolder_skip_appledouble_sidecars(tmp_path):
    cbr_path = _copy_cbr("nested_pages.rar5.cbr", tmp_path / "nested.cbr")
    assert archive.list_book_pages(cbr_path, BookFormat.CBR).page_count == 2
    page = archive.extract_page(cbr_path, BookFormat.CBR, 1, tmp_path / "cache")
    assert page.read_bytes() == _PAGE_BYTES + b" 0002"


def test_read_rar_member_handles_solid_rar3(tmp_path):
    rar_path = _copy_cbr("rar3_solid_from_rarfile.rar", tmp_path / "solid.rar")
    assert archive.read_rar_member(rar_path, "stest2.txt").startswith(b"000\n001\n")


def test_read_rar_member_falls_back_to_bsdtar(tmp_path, monkeypatch):
    import rarfile

    cbr_path = _copy_cbr("three_pages.rar5.cbr", tmp_path / "book.cbr")

    def broken_read(self, member):
        raise rarfile.RarExecError("simulated unar failure")

    monkeypatch.setattr(rarfile.RarFile, "read", broken_read)
    assert archive.read_rar_member(cbr_path, "0001.png") == _PAGE_BYTES + b" 0001"


def test_extract_page_out_of_range_raises(tmp_path):
    cbr_path = _copy_cbr("three_pages.rar5.cbr", tmp_path / "book.cbr")
    with pytest.raises(archive.ArchiveError):
        archive.extract_page(cbr_path, BookFormat.CBR, 3, tmp_path / "cache")
    with pytest.raises(IndexError):
        archive.extract_page(cbr_path, BookFormat.CBR, -1, tmp_path / "cache")


def test_pages_are_in_natural_order_without_mac_resource_forks(tmp_path):
    names = ["10.jpg", "2.jpg", "1.jpg", "__MACOSX/._1.jpg", "._2.jpg", "ComicInfo.xml", "notes.txt"]
    with formats.open_archive(_write_cbz(tmp_path / "book.cbz", names)) as book:
        assert [e.name for e in book.pages()] == ["1.jpg", "2.jpg", "10.jpg"]


def test_same_file_name_in_two_folders_are_two_pages(tmp_path):
    cbz_path = _write_cbz(tmp_path / "book.cbz", ["ch1/001.jpg", "ch2/001.jpg"])
    cache = tmp_path / "cache"
    first = archive.extract_page(cbz_path, BookFormat.CBZ, 0, cache)
    second = archive.extract_page(cbz_path, BookFormat.CBZ, 1, cache)
    assert first != second
    assert (first.read_bytes(), second.read_bytes()) == (_PAGE_BYTES + b" ch1/001.jpg", _PAGE_BYTES + b" ch2/001.jpg")


def test_the_container_is_recognised_by_content_not_extension(tmp_path):
    mislabelled = _write_cbz(tmp_path / "actually-a-zip.cbr", 2)
    info = archive.list_book_pages(mislabelled, BookFormat.CBR)
    assert (info.page_count, info.decoder_used) == (2, "zip")
    rar_as_cbz = _copy_cbr("three_pages.rar5.cbr", tmp_path / "actually-a-rar.cbz")
    assert archive.list_book_pages(rar_as_cbz, BookFormat.CBZ).decoder_used == "rar"
    garbage = tmp_path / "garbage.cbz"
    garbage.write_bytes(b"not an archive at all")
    with pytest.raises(archive.ArchiveError):
        archive.list_book_pages(garbage, BookFormat.CBZ)


def test_cb7_pages_and_sidecar(tmp_path):
    import py7zr

    path = tmp_path / "book.cb7"
    with py7zr.SevenZipFile(path, "w") as z:
        for name in ("p/10.png", "p/2.png"):
            z.writestr(_PAGE_BYTES + name.encode(), name)
        z.writestr(b"<ComicInfo><Series>Harbour Lights</Series></ComicInfo>", "ComicInfo.xml")
    assert archive.list_book_pages(path, BookFormat.CB7).page_count == 2
    assert archive.extract_page(path, BookFormat.CB7, 0, tmp_path / "cache").read_bytes() == _PAGE_BYTES + b"p/2.png"
    with archive.open_book(path, BookFormat.CB7) as book:
        assert b"Harbour Lights" in (book.sidecar("comicinfo.xml") or b"")


def test_entry_names_never_escape_the_page_cache(tmp_path):
    cbz_path = _write_cbz(tmp_path / "evil.cbz", ["../../../../escaped.png", "/abs/escaped2.png"])
    cache = tmp_path / "deep" / "cache"
    pages = [archive.extract_page(cbz_path, BookFormat.CBZ, i, cache) for i in range(2)]
    assert all(p.parent == cache for p in pages)
    assert not list(tmp_path.rglob("escaped*"))


def test_decompression_bombs_are_refused(tmp_path, monkeypatch):
    bomb = tmp_path / "bomb.cbz"
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("001.jpg", b"\0" * (8 * 1024 * 1024))  # 8 MiB of zeros, a few KiB compressed
    with formats.open_archive(bomb) as book, pytest.raises(formats.UnsafeArchive):
        book.read("001.jpg")
    monkeypatch.setattr(formats, "MAX_ENTRY_BYTES", 1024)
    with formats.open_archive(_write_cbz(tmp_path / "big.cbz", ["001.jpg"], data=b"x" * 4096)) as book:
        with pytest.raises(formats.UnsafeArchive):
            book.read("001.jpg")
    monkeypatch.setattr(formats, "MAX_ENTRIES", 3)
    with pytest.raises(formats.UnsafeArchive):
        formats.open_archive(_write_cbz(tmp_path / "many.cbz", 5))


def test_image_folder(tmp_path):
    folder = tmp_path / "Harbour Lights v01"
    folder.mkdir()
    for name in ("10.jpg", "2.jpg", "._2.jpg", "ComicInfo.xml"):
        (folder / name).write_bytes(_PAGE_BYTES)
    assert [p.name for p in archive.list_image_folder_pages(folder)] == ["2.jpg", "10.jpg"]
    assert archive.list_book_pages(folder, BookFormat.IMAGE_FOLDER).page_count == 2
