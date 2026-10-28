"""The v1 archive API on top of kodex.formats.archive, which does the work
(CBZ, CBR, CB7 and image folders, recognised by content, pages in natural
order, bounded reads). Kept for the v1 modules that still call it."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.models.enums import BookFormat
from kodex.formats import archive as _archive
from kodex.formats.archive import IMAGE_EXTENSIONS, Archive, ArchiveError, PageOutOfRange, UnsafeArchive

__all__ = [
    "IMAGE_EXTENSIONS", "ArchiveError", "ArchiveInfo", "UnsafeArchive", "extract_page", "list_book_pages",
    "list_image_folder_pages", "open_book",
]  # fmt: skip


@dataclass
class ArchiveInfo:
    page_count: int
    decoder_used: str  # "zip" | "rar" | "7z" | "folder"


def _is_image(name: str) -> bool:
    return _archive.is_page(name)


def _ensure_rar_tools() -> None:
    settings = get_settings()
    if (_archive.RAR_TOOLS["unar"], _archive.RAR_TOOLS["bsdtar"]) != (settings.unar_binary, settings.bsdtar_binary):
        _archive.configure_rar_tools(settings.unar_binary, settings.bsdtar_binary)


def open_book(path: Path, file_format: BookFormat) -> Archive:
    """The book's archive (or image folder), whatever its extension says."""
    if file_format not in (BookFormat.CBZ, BookFormat.CBR, BookFormat.CB7, BookFormat.IMAGE_FOLDER):
        raise ValueError(f"{file_format} is not read page by page")
    _ensure_rar_tools()
    return _archive.open_archive(path)


def list_image_folder_pages(path: Path) -> list[Path]:
    """Sorted page images directly inside an image-folder book."""
    with _archive.FolderArchive(path) as folder:
        return folder.page_paths()


def _list_cbz_images(path: Path) -> list[str]:
    with _archive.ZipArchive(path) as book:
        return [entry.name for entry in book.pages()]


def read_rar_member(path: Path, member: str) -> bytes:
    _ensure_rar_tools()
    with _archive.open_archive(path) as book:
        return book.read(member)


def list_book_pages(path: Path, file_format: BookFormat) -> ArchiveInfo:
    with open_book(path, file_format) as book:
        kind = {
            _archive.ZipArchive: "zip", _archive.RarArchive: "rar", _archive.SevenZipArchive: "7z",
        }.get(type(book), "folder")  # fmt: skip
        return ArchiveInfo(page_count=len(book.pages()), decoder_used=kind)


def extract_page(path: Path, file_format: BookFormat, page_index: int, dest_dir: Path) -> Path:
    """Extracts one page (0-indexed) into ``dest_dir``, a per-book cache that
    persists across requests, and returns its path. The file is named after
    the page's index, never the entry's own name, so a hostile entry name
    can't write outside the cache and two pages called ``001.jpg`` in
    different folders can't overwrite each other."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with open_book(path, file_format) as book:
        pages = book.pages()
        if page_index < 0 or page_index >= len(pages):
            raise PageOutOfRange(f"Page {page_index} out of range")
        entry = pages[page_index]
        out_path = dest_dir / f"page-{page_index:05d}{Path(entry.name).suffix.lower()}"
        if out_path.is_file() and out_path.stat().st_size > 0:
            return out_path
        data = book.read(entry.name)
    # Written under a temporary name first: a process killed mid-write must
    # not leave a truncated page that the check above would then serve.
    partial = out_path.with_name(out_path.name + ".part")
    partial.write_bytes(data)
    partial.replace(out_path)
    return out_path
