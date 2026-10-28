"""Walks a Library's folder tree and creates/updates Book + BookMetadata
rows. Idempotent: rescanning skips files whose size and mtime haven't
changed since the last scan.

A scan has three passes. The walk lists every book on disk and compares
it with the library's books, loaded in one query, so an unchanged file
costs a stat and nothing else. New and changed files are then read by
kodex.library.inspect, in a process pool when there are many, while this
process writes the results: one savepoint per book (a bad file loses only
itself) and a commit every few hundred. Last, books whose file is gone are
hidden and names parsed by an older parser are parsed again.

Which series a book goes into is decided by kodex.matching.group from the
library's grouping strategy (one series per folder, or by embedded
metadata and file name). A book already in a series is never moved here:
a changed key becomes a regroup proposal in the review queue. A file that
moved, or was converted to another format, keeps its book (and progress)
when its pages are recognised.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.book import Book
from app.models.enums import BookFormat, MetadataSource
from app.models.library import Library
from app.models.metadata import BookMetadata
from app.scanning import archive
from kodex.library.duplicates import mark_exact as mark_exact_duplicates
from kodex.library.inspect import CHEAP_DIMENSION_FORMATS, FileFacts, inspect_file
from kodex.library.inspect import build_metadata_fields as _build_metadata_fields
from kodex.library.inspect import extract_comicinfo as _extract_comicinfo
from kodex.library.models import BookFileHash
from kodex.matching.books import apply_parsed, reparse_stale
from kodex.matching.group import book_kind, collected_by_size, parse_book_name, series_key
from kodex.matching.series_ops import check_grouping, place_book

__all__ = ["EXTENSION_TO_FORMAT", "ScanStats", "_build_metadata_fields", "_extract_comicinfo", "scan_library"]

logger = logging.getLogger(__name__)

EXTENSION_TO_FORMAT = {
    ".epub": BookFormat.EPUB,
    ".pdf": BookFormat.PDF,
    ".cbz": BookFormat.CBZ,
    ".cbr": BookFormat.CBR,
    ".cb7": BookFormat.CB7,
}
IMAGE_EXTENSIONS = archive.IMAGE_EXTENSIONS
# Below this many files to read, a process pool costs more than it saves.
_POOL_MIN_FILES = 32
_COMMIT_EVERY = 250


@dataclass
class ScanStats:
    books_added: int = 0
    books_updated: int = 0
    books_unchanged: int = 0
    series_created: int = 0
    # Books whose file was gone this scan (newly hidden), and hidden books
    # whose file turned up again (shown again) — see _sync_missing_books.
    books_hidden: int = 0
    books_restored: int = 0
    # Ids of books this scan added (new files, not changed ones) — see
    # scan_library_task's push notifications for followed series.
    new_book_ids: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class _Known:
    """A book of the library as it stood when the scan began."""

    id: int
    path: str
    size: int | None
    mtime: float | None
    content_hash: str | None
    content_id: str | None
    file_format: BookFormat
    missing: bool
    keep_visible: bool


def _is_image_only_dir(dir_path: Path) -> bool:
    """True if dir_path has at least one image file directly inside it, so
    it is one "loose images" book. Its subfolders (credits, notes: common in
    scanlation releases) don't stop that, and aren't read as pages either."""
    for entry in dir_path.iterdir():
        if entry.is_file() and entry.suffix.lower() in IMAGE_EXTENSIONS:
            return True
    return False


def _walk(root: Path, libraries_root: Path) -> Iterator[tuple[Path, str, BookFormat]]:
    """Every book under ``root``: (absolute path, path relative to root,
    format)."""
    for dirpath, dirnames, filenames in os.walk(root):
        current_dir = Path(dirpath)
        # _sorterat is a second bind mount nested inside libraries_root, so a
        # library whose root is libraries_root itself (the sorting intake,
        # path ".") would otherwise walk every already-sorted book too.
        if current_dir == libraries_root and "_sorterat" in dirnames:
            dirnames.remove("_sorterat")
        if current_dir != root and _is_image_only_dir(current_dir):
            dirnames[:] = []
            yield current_dir, str(current_dir.relative_to(root)), BookFormat.IMAGE_FOLDER
            continue
        for filename in filenames:
            file_format = EXTENSION_TO_FORMAT.get(Path(filename).suffix.lower())
            if file_format is not None:
                abs_path = current_dir / filename
                yield abs_path, str(abs_path.relative_to(root)), file_format


def _load_known(db: Session, library: Library) -> dict[str, _Known]:
    rows = db.execute(
        select(Book.id, Book.file_path, Book.file_size, Book.file_mtime, Book.content_hash, Book.content_id,
               Book.file_format, Book.missing_since, Book.keep_visible_when_missing)
        .where(Book.library_id == library.id)
    )  # fmt: skip
    return {
        r.file_path: _Known(r.id, r.file_path, r.file_size, r.file_mtime, r.content_hash, r.content_id, r.file_format,
                            r.missing_since is not None, bool(r.keep_visible_when_missing))
        for r in rows
    }  # fmt: skip


def _inspect_all(jobs: list[tuple[Path, str, BookFormat, bool]], workers: int,
                 rar_tools: tuple[str, str]) -> Iterator[FileFacts]:  # fmt: skip
    if workers <= 1 or len(jobs) < _POOL_MIN_FILES:
        for abs_path, relative, file_format, ids_only in jobs:
            yield inspect_file(str(abs_path), relative, file_format.value, ids_only=ids_only, rar_tools=rar_tools)
        return
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = (
            pool.submit(
                inspect_file, str(abs_path), relative, file_format.value, ids_only=ids_only, rar_tools=rar_tools
            )
            for abs_path, relative, file_format, ids_only in jobs
        )
        # Submitted a window at a time, so a huge first scan doesn't hold
        # every result in memory before the first one is written.
        window: list = []
        for future in futures:
            window.append(future)
            if len(window) >= workers * 8:
                yield window.pop(0).result()
        for future in window:
            yield future.result()


def _remember_file_hash(db: Session, book: Book) -> None:
    """Keeps the book's current KOReader id mapped to it for good: a device
    that read the file before it changed still sends that id."""
    if book.id is None or not book.content_hash:
        return
    db.execute(
        pg_insert(BookFileHash)
        .values(book_id=book.id, kind="koreader", value=book.content_hash)
        .on_conflict_do_nothing(index_elements=["kind", "value"])
    )


class _Moves:
    """Books whose file is gone this scan, by content id and by KOReader
    id, for recognising a file that moved (or was converted)."""

    def __init__(self, gone: list[_Known]) -> None:
        self.by_content: dict[str, list[_Known]] = {}
        self.by_hash: dict[tuple[str, BookFormat], list[_Known]] = {}
        for known in gone:
            if known.content_id:
                self.by_content.setdefault(known.content_id, []).append(known)
            elif known.content_hash:
                self.by_hash.setdefault((known.content_hash, known.file_format), []).append(known)
        self.moved: set[int] = set()

    def take(self, facts: FileFacts) -> _Known | None:
        candidates = self.by_content.get(facts.content_id or "", []) or self.by_hash.get(
            (facts.koreader_id or "", facts.file_format), []
        )
        for known in candidates:
            if known.id not in self.moved:
                self.moved.add(known.id)
                return known
        return None


def _apply(db: Session, library: Library, facts: FileFacts, known: _Known | None, moves: _Moves,
           stats: ScanStats) -> None:  # fmt: skip
    relative_path = Path(facts.relative_path)
    if known is None and (moved := moves.take(facts)) is not None:
        logger.info("%s moved to %s", moved.path, relative_path)
        known = moved
    book = db.get(Book, known.id) if known is not None else None
    is_new = book is None
    if book is None:
        book = Book(library_id=library.id, file_path=facts.relative_path, file_format=facts.file_format)
    book.file_path = facts.relative_path
    book.file_format = facts.file_format
    book.file_size = facts.size
    book.file_mtime = facts.mtime
    book.content_hash = facts.koreader_id
    book.content_id = facts.content_id
    book.cover_key = None  # a changed file may have another cover
    # A changed CBR's old sizes may be wrong; the next open recomputes them.
    book.page_dimensions = facts.page_dimensions if facts.file_format in CHEAP_DIMENSION_FORMATS else None
    if facts.page_count is not None:
        book.page_count = facts.page_count
    for error in facts.errors:
        logger.warning("%s: %s", facts.relative_path, error)
    db.add(book)
    db.flush()
    _remember_file_hash(db, book)

    meta_fields = dict(facts.meta_fields)
    meta_fields.pop("number", None)
    embedded = facts.embedded
    kind = book_kind(library.library_type.value, facts.file_format.value, embedded)
    parsed = collected_by_size(parse_book_name(relative_path, kind), kind, book.page_count, embedded)
    apply_parsed(book, kind, parsed, embedded)
    key = series_key(
        strategy=library.grouping_strategy, kind=kind, relative_path=relative_path, parsed=parsed, embedded=embedded
    )
    if is_new or book.series_id is None:
        series = place_book(db, library, book, key)
        book.series_id = series.id if series else None
    else:
        check_grouping(db, library, book, key)

    meta_fields.pop("series", None)  # informational only, not stored yet
    meta_fields.pop("spine_item_count", None)
    if book.book_metadata is None:
        book.book_metadata = BookMetadata(book_id=book.id, source=MetadataSource.EMBEDDED, **meta_fields)
    else:
        for field_name, value in meta_fields.items():
            if field_name not in (book.book_metadata.locked_fields or []):
                setattr(book.book_metadata, field_name, value)
    # Everything the file says about itself, for the matching engine.
    book.book_metadata.raw = embedded or None
    db.add(book)
    db.flush()
    if is_new:
        stats.books_added += 1
        stats.new_book_ids.append(book.id)
    else:
        stats.books_updated += 1


def _backfill_ids(db: Session, known: _Known, facts: FileFacts) -> None:
    book = db.get(Book, known.id)
    if book is None:
        return
    if book.content_hash is None:
        book.content_hash = facts.koreader_id
        db.flush()
        _remember_file_hash(db, book)
    if book.content_id is None:
        book.content_id = facts.content_id


def scan_library(db: Session, library: Library, *, workers: int | None = None) -> ScanStats:
    settings = get_settings()
    root = settings.libraries_root / library.path
    stats = ScanStats()
    if not root.is_dir():
        stats.errors.append(f"Library path does not exist: {root}")
        return stats
    if workers is None:
        workers = getattr(settings, "scan_workers", 0) or os.cpu_count() or 1
    rar_tools = (getattr(settings, "unar_binary", "unar"), getattr(settings, "bsdtar_binary", "bsdtar"))

    known = _load_known(db, library)
    # Every book path seen on disk, including ones that then fail to read: a
    # file that errors still exists and must not be hidden as missing.
    seen: set[str] = set()
    jobs: list[tuple[Path, str, BookFormat, bool]] = []
    for abs_path, relative, file_format in _walk(root, settings.libraries_root):
        seen.add(relative)
        try:
            stat = abs_path.stat()
        except OSError as exc:
            stats.errors.append(f"{abs_path}: {exc}")
            continue
        book = known.get(relative)
        if book is not None and book.size == stat.st_size and book.mtime == stat.st_mtime:
            stats.books_unchanged += 1
            if book.content_hash is None or book.content_id is None:
                jobs.append((abs_path, relative, file_format, True))  # ids for books scanned before they existed
            continue
        jobs.append((abs_path, relative, file_format, False))

    moves = _Moves([k for path, k in known.items() if path not in seen])
    done = 0
    for facts in _inspect_all(jobs, workers, rar_tools):
        try:
            with db.begin_nested():
                if facts.ids_only:
                    _backfill_ids(db, known[facts.relative_path], facts)
                else:
                    _apply(db, library, facts, known.get(facts.relative_path), moves, stats)
        except Exception as exc:
            logger.exception("Failed to process %s", facts.relative_path)
            stats.errors.append(f"{root / facts.relative_path}: {exc}")
        done += 1
        if done % _COMMIT_EVERY == 0:
            db.commit()
    db.commit()
    _sync_missing_books(db, library, known, seen, moves.moved, stats)
    # Books scanned before this parser version (or carried over from v1)
    # get their names parsed and their series keys now; no network.
    reparse_stale(db, library, root)
    mark_exact_duplicates(db)
    db.commit()
    return stats


def _sync_missing_books(db: Session, library: Library, known: dict[str, _Known], seen: set[str], moved: set[int],
                        stats: ScanStats) -> None:  # fmt: skip
    """Hides books whose file wasn't found this scan and shows hidden ones
    whose file is back (see Book.missing_since). Never deletes anything:
    progress, metadata and collection memberships all survive, so a file
    that comes back — or an admin's "Visa igen" — restores the book as it
    was. Only the books that change are loaded."""
    if not seen and known:
        # An empty walk of a library that has books is far more likely an
        # unmounted network share than every file being gone: hide nothing.
        message = f"Inga filer hittades i {library.name} — döljer inget (är disken monterad?)"
        logger.warning(message)
        stats.errors.append(message)
        return
    now = dt.datetime.now(dt.UTC)
    for path, entry in known.items():
        if entry.id in moved:
            continue
        if path in seen:
            if not entry.missing and not entry.keep_visible:
                continue
            book = db.get(Book, entry.id)
            if book is None:
                continue
            if entry.missing:
                book.missing_since = None
                book.keep_visible_when_missing = False
                stats.books_restored += 1
            else:
                # Shown by hand while missing, and the file is back: from now
                # on it hides again normally if it disappears.
                book.keep_visible_when_missing = False
        elif not entry.missing and not entry.keep_visible:
            book = db.get(Book, entry.id)
            if book is None:
                continue
            book.missing_since = now
            stats.books_hidden += 1
    db.commit()
