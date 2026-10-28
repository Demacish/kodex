"""Writing what Kodex knows back into the files, opt-in per library
(``Library.write_back``) and never in a read-only one.

ComicInfo.xml goes into CBZ archives: the archive is rewritten with every
other entry copied as it was and the new ComicInfo.xml merged into the old
one (kodex.formats.comicinfo), then swapped in atomically. The pages don't
change, so neither does the content id: the book, its progress and its
duplicates are the same afterwards, and the KOReader id the file had is
kept as an alias. CBR and CB7 can't be rewritten in place; they can be
converted to CBZ first, the original left next to it until a person
deletes it (it shows up as an exact duplicate of the converted book).
series.json (Mylar3's format plus Kodex's backup) goes into each series
folder.
"""

from __future__ import annotations

import logging
import os
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.book import Book
from app.models.enums import ARCHIVE_FORMATS, BookFormat
from app.models.library import Library
from kodex.formats import archive
from kodex.formats.comicinfo import build_comicinfo_xml
from kodex.formats.identity import content_id, koreader_partial_md5
from kodex.library.paths import within

logger = logging.getLogger(__name__)


class WriteBackRefused(RuntimeError):
    """The library doesn't allow writing into its files."""


def check_writable(library: Library, *, write_back: bool = True) -> None:
    if library.read_only:
        raise WriteBackRefused(f"{library.name} is read-only")
    if write_back and not library.write_back:
        raise WriteBackRefused(f"Writing metadata back is off for {library.name}")


def comicinfo_values(book: Book) -> dict[str, str | int | None]:
    """The ComicInfo elements Kodex sets for a book (None removes one)."""
    meta, series = book.book_metadata, book.series
    external = (meta.external_ids if meta else None) or {}
    issue_id = external.get("comicvine_issue_id")
    values: dict[str, str | int | None] = {
        "Series": series.title if series else None,
        "Number": book.number_label,
        "Volume": series.start_year if series and series.start_year else None,
        "Year": meta.published_year if meta else None,
        "Summary": meta.summary if meta else None,
        "Publisher": (meta.publisher if meta else None) or (series.publisher if series else None),
        "Writer": ", ".join(meta.authors) if meta and meta.authors else None,
        "Genre": ", ".join(meta.genres) if meta and meta.genres else None,
        "LanguageISO": meta.language if meta else None,
        "StoryArc": ", ".join(meta.story_arcs) if meta and meta.story_arcs else None,
    }
    if meta is not None and meta.title and meta.title != Path(book.file_path).stem:
        values["Title"] = meta.title
    if series is not None and series.format_family == "manga":
        values["Manga"] = "YesAndRightToLeft"
    if issue_id:
        # ComicTagger's way, which other tools (and kodex.matching.identify) read.
        values["Web"] = f"https://comicvine.gamespot.com/issue/4000-{issue_id}/"
        values["Notes"] = f"Tagged with Kodex using info from Comic Vine. [Issue ID {issue_id}]"
    return values


def _is_comicinfo(name: str) -> bool:
    return PurePosixPath(name.replace("\\", "/")).name.lower() == "comicinfo.xml"


def rewrite_cbz(path: Path, comicinfo: bytes) -> None:
    """Replaces the CBZ at ``path`` with a copy whose ComicInfo.xml (at the
    archive's root) is ``comicinfo``; every other entry is copied with its
    name, date and compression. The original stays until the copy is
    complete."""
    partial = path.with_name(f".{path.name}.kodex-part")
    try:
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(partial, "w") as target:
            for info in source.infolist():
                if _is_comicinfo(info.filename):
                    continue
                with source.open(info) as data:
                    target.writestr(info, data.read(), compress_type=info.compress_type)
            target.writestr(zipfile.ZipInfo("ComicInfo.xml", date_time=(2026, 1, 1, 0, 0, 0)), comicinfo,
                            compress_type=zipfile.ZIP_DEFLATED)  # fmt: skip
        os.chmod(partial, os.stat(path).st_mode)
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)


def _refresh_file(db: Session, book: Book, path: Path) -> None:
    """The book's record after its file was rewritten, so the next scan
    sees no change, with its old KOReader id kept as an alias."""
    from app.scanning.scanner import _remember_file_hash

    _remember_file_hash(db, book)
    stat = path.stat()
    book.file_size, book.file_mtime = stat.st_size, stat.st_mtime
    book.content_hash = koreader_partial_md5(path)
    db.flush()
    _remember_file_hash(db, book)


def write_comicinfo(db: Session, book: Book, libraries_root: Path) -> bool:
    """Writes the book's ComicInfo.xml if it differs from the file's; True
    when the file was rewritten."""
    check_writable(book.library)
    if book.file_format != BookFormat.CBZ:
        return False
    path = within(libraries_root, book.library.path, book.file_path)
    with archive.open_archive(path) as current:
        existing = current.sidecar("ComicInfo.xml")
    wanted = build_comicinfo_xml(comicinfo_values(book), existing)
    if existing == wanted:
        return False
    identity = book.content_id
    rewrite_cbz(path, wanted)
    if identity and content_id(path, BookFormat.CBZ) != identity:
        logger.error("Writing ComicInfo into %s changed its pages", path)  # rewrite_cbz never touches them
    _refresh_file(db, book, path)
    meta = book.book_metadata
    if meta is not None:
        meta.raw = {**(meta.raw or {}), "comicinfo": _parsed(wanted)}
    return True


def _parsed(data: bytes) -> dict[str, Any]:
    from kodex.formats.comicinfo import parse_comicinfo_xml

    return parse_comicinfo_xml(data)


def write_back_library(db: Session, library: Library, libraries_root: Path) -> dict[str, int]:
    """ComicInfo.xml into every CBZ and series.json into every series folder
    of the library."""
    from app.models.series import Series
    from app.scanning.series_json import export_series
    from kodex.matching.config import get_config

    check_writable(library)
    which = get_config().write_back
    written = unchanged = failed = 0
    books = db.scalars(select(Book).where(Book.library_id == library.id, Book.missing_since.is_(None)))
    for book in books if which.get("comicinfo", True) else []:
        try:
            if write_comicinfo(db, book, libraries_root):
                written += 1
            else:
                unchanged += 1
        except Exception:
            failed += 1
            logger.exception("Could not write ComicInfo into %s", book.file_path)
        db.commit()
    series_files = 0
    all_series = db.scalars(select(Series).where(Series.library_id == library.id))
    for series in all_series if which.get("series_json", True) else []:
        if export_series(series, libraries_root=libraries_root) is not None:
            series_files += 1
    db.commit()
    return {"comicinfo_written": written, "unchanged": unchanged, "failed": failed, "series_json": series_files}


def convert_to_cbz(db: Session, book: Book, libraries_root: Path) -> Path:
    """Writes a CBZ with every entry of the book's CBR or CB7 next to it and
    makes the book that CBZ. The original stays where it was."""
    check_writable(book.library, write_back=False)
    if book.file_format not in ARCHIVE_FORMATS or book.file_format == BookFormat.CBZ:
        raise ValueError(f"{book.file_path} is not a CBR or CB7")
    source = within(libraries_root, book.library.path, book.file_path)
    target = source.with_suffix(".cbz")
    if target.exists():
        raise FileExistsError(f"{target.name} already exists")
    partial = target.with_name(f".{target.name}.kodex-part")
    try:
        with archive.open_archive(source) as original, zipfile.ZipFile(partial, "w") as cbz:
            for entry in original.entries():
                compression = zipfile.ZIP_STORED if archive.is_page(entry.name) else zipfile.ZIP_DEFLATED
                cbz.writestr(zipfile.ZipInfo(entry.name, date_time=(2026, 1, 1, 0, 0, 0)), original.read(entry.name),
                             compress_type=compression)  # fmt: skip
        if book.content_id and content_id(partial, BookFormat.CBZ) != book.content_id:
            raise archive.ArchiveError(f"The CBZ of {source.name} doesn't have the same pages")
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    book.file_path = str(Path(book.file_path).with_suffix(".cbz"))
    book.file_format = BookFormat.CBZ
    _refresh_file(db, book, target)
    return target
