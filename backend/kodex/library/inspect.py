"""Everything a scan learns from one book file, without the database: its
two ids, pages, page sizes and embedded metadata. A plain function of the
path, so scans can run it in a process pool and keep the database work
in one place (app/scanning/scanner.py).
"""

from __future__ import annotations

import logging
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.models.enums import ARCHIVE_FORMATS, BookFormat
from kodex.formats import archive

logger = logging.getLogger(__name__)

# Page sizes are cheap where an image's header can be read straight from
# the container; CBR and CB7 need each page unpacked, so a background job
# sizes them the first time the book is opened.
CHEAP_DIMENSION_FORMATS = (BookFormat.CBZ, BookFormat.IMAGE_FOLDER)


@dataclass
class FileFacts:
    relative_path: str
    file_format: BookFormat
    size: int
    mtime: float
    koreader_id: str | None = None
    content_id: str | None = None
    page_count: int | None = None
    page_dimensions: list[list[int] | None] | None = None
    meta_fields: dict[str, Any] = field(default_factory=dict)
    embedded: dict[str, Any] = field(default_factory=dict)
    ids_only: bool = False
    errors: list[str] = field(default_factory=list)


def extract_comicinfo(path: Path, file_format: BookFormat) -> dict[str, Any]:
    """v1's ComicInfo fields (app/scanning/parsers/comicinfo.py) of an
    archive; empty when there is none or it can't be read."""
    from app.scanning.parsers.comicinfo import parse_comicinfo

    if file_format not in ARCHIVE_FORMATS:
        return {}
    try:
        with archive.open_archive(path) as book:
            data = book.sidecar("ComicInfo.xml")
        return parse_comicinfo(data) if data else {}
    except Exception as exc:  # noqa: BLE001 - metadata extraction must never abort a scan
        logger.warning("ComicInfo.xml extraction failed for %s: %s", path, exc)
        return {}


def build_metadata_fields(path: Path, file_format: BookFormat, fallback_title: str) -> dict[str, Any]:
    """The BookMetadata fields the file gives. Never raises: on any parser
    error the title falls back to the file name."""
    from app.scanning.parsers.epub_meta import parse_epub_metadata
    from app.scanning.parsers.pdf_meta import parse_pdf_metadata

    fields: dict[str, Any] = {"title": fallback_title, "authors": [], "genres": [], "tags": [], "story_arcs": []}
    try:
        if file_format == BookFormat.EPUB:
            fields.update(parse_epub_metadata(path))
        elif file_format == BookFormat.PDF:
            fields.update(parse_pdf_metadata(path))
        elif file_format in ARCHIVE_FORMATS:
            fields.update(extract_comicinfo(path, file_format))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Metadata parsing failed for %s (%s): falling back to filename", path, exc)
    fields.setdefault("sort_title", fields["title"])
    # ComicInfo's "manga" field has no BookMetadata column.
    fields.pop("manga", None)
    return fields


def _page_dimensions(book: archive.Archive) -> list[list[int] | None]:
    from PIL import Image

    sizes: list[list[int] | None] = []
    for entry in book.pages():
        try:
            with book.open(entry.name) as handle, Image.open(handle) as image:
                sizes.append([int(image.size[0]), int(image.size[1])])
        except Exception:  # noqa: BLE001 - one unreadable page mustn't lose the rest
            sizes.append(None)
    return sizes


def inspect_file(abs_path: str, relative_path: str, file_format: str, *, ids_only: bool = False,
                 rar_tools: tuple[str, str] | None = None) -> FileFacts:  # fmt: skip
    """What the file at ``abs_path`` is. Never raises: whatever can't be
    read is left empty and noted in ``errors``. With ``ids_only`` (an
    unchanged file scanned before its ids existed) only the ids are read."""
    from kodex.formats.embedded import read_embedded
    from kodex.formats.identity import content_id, koreader_id

    if rar_tools is not None and (archive.RAR_TOOLS["unar"], archive.RAR_TOOLS["bsdtar"]) != rar_tools:
        archive.configure_rar_tools(*rar_tools)
    path = Path(abs_path)
    fmt = BookFormat(file_format)
    stat = os.stat(path)
    facts = FileFacts(relative_path, fmt, stat.st_size, stat.st_mtime, ids_only=ids_only)
    try:
        facts.koreader_id = koreader_id(path, fmt)
    except OSError as exc:
        facts.errors.append(f"KOReader id: {exc}")
    try:
        facts.content_id = content_id(path, fmt)
    except (OSError, archive.ArchiveError, zipfile.BadZipFile) as exc:
        facts.errors.append(f"content id: {exc}")
    if ids_only:
        return facts
    if fmt in (*ARCHIVE_FORMATS, BookFormat.IMAGE_FOLDER):
        try:
            with archive.open_archive(path) as book:
                facts.page_count = len(book.pages())
                if fmt in CHEAP_DIMENSION_FORMATS:
                    facts.page_dimensions = _page_dimensions(book)
        except (OSError, archive.ArchiveError, zipfile.BadZipFile) as exc:
            facts.errors.append(f"pages: {exc}")
    facts.meta_fields = build_metadata_fields(path, fmt, fallback_title=path.stem)
    if fmt == BookFormat.PDF and "page_count" in facts.meta_fields:
        facts.page_count = facts.meta_fields.pop("page_count")
    facts.embedded = read_embedded(path, fmt)
    return facts
