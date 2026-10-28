"""Book-level fields the matching engine derives from a file name and its
embedded metadata, and the reparse pass that fills them in for books that
were scanned before (or by v1)."""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.book import Book
from app.models.enums import BookEditionType
from app.models.library import Library
from app.models.series import Series
from kodex.formats.embedded import read_embedded
from kodex.matching.group import Strategy, book_format, book_kind, collected_by_size, parse_book_name, series_key
from kodex.matching.parse import PARSER_VERSION, Kind, ParsedName, normalize_number
from kodex.matching.series_ops import check_grouping, place_book

logger = logging.getLogger(__name__)

_EMBEDDED_KEYS = ("comicinfo", "metroninfo", "opf", "pdf")


def sort_number(label: str | None) -> float | None:
    """The numeric sort key of a number label (``"1.MU"`` sorts as 1)."""
    if not label:
        return None
    try:
        return float(label)
    except ValueError:
        head = label.split(".")[0].rstrip("abcdefghijklmnopqrstuvwxyz")
        try:
            return float(head)
        except ValueError:
            return None


def apply_parsed(book: Book, kind: Kind, parsed: ParsedName, embedded: dict[str, Any]) -> None:
    """Stores what the file name and embedded metadata say about the
    book's number, volume, chapter and format. ComicInfo's ``Number`` wins
    over the file name."""
    book.parsed = {**asdict(parsed), "version": PARSER_VERSION}
    book.format = book_format(kind, parsed, embedded)
    book.edition_type = BookEditionType.COLLECTED if book.format == "collected" else BookEditionType.ISSUE
    book.volume_number = parsed.volume
    book.chapter_number = parsed.chapter
    book.scan_group = parsed.scan_group
    comicinfo_number = (embedded.get("comicinfo") or {}).get("number")
    label = normalize_number(str(comicinfo_number)) if comicinfo_number else None
    if label is None:
        label = (parsed.chapter or parsed.volume) if kind == "manga" else (parsed.issue or parsed.volume)
    book.number_label = label
    book.number = sort_number(label)


def _embedded_for(book: Book, root: Path) -> dict[str, Any]:
    raw = book.book_metadata.raw if book.book_metadata is not None else None
    if raw and any(key in raw for key in _EMBEDDED_KEYS):
        return {key: raw[key] for key in _EMBEDDED_KEYS if key in raw}
    path = root / book.file_path
    if not path.exists():
        return {}
    embedded = read_embedded(path, book.file_format)
    if book.book_metadata is not None:
        book.book_metadata.raw = {**(raw or {}), **embedded} or None
    return embedded


def reparse_book(db: Session, library: Library, book: Book, root: Path) -> None:
    embedded = _embedded_for(book, root)
    kind = book_kind(library.library_type.value, book.file_format.value, embedded)
    relative = Path(book.file_path)
    parsed = collected_by_size(parse_book_name(relative, kind), kind, book.page_count, embedded)
    apply_parsed(book, kind, parsed, embedded)
    strategy: Strategy = library.grouping_strategy  # type: ignore[assignment]
    key = series_key(strategy=strategy, kind=kind, relative_path=relative, parsed=parsed, embedded=embedded)
    if book.series_id is None:
        series = place_book(db, library, book, key)
        book.series_id = series.id if series else None
    else:
        check_grouping(db, library, book, key)


def remove_empty_series(db: Session, library: Library) -> int:
    """Deletes series without a single book, not even a hidden one (v1
    left them behind when it merged series). Nothing is lost: progress and
    collections belong to books."""
    has_books = select(Book.id).where(Book.series_id == Series.id).exists()
    empty = list(db.scalars(select(Series).where(Series.library_id == library.id, ~has_books)))
    for series in empty:
        db.delete(series)
    if empty:
        db.flush()
        logger.info("Removed %d empty series from %s", len(empty), library.name)
    return len(empty)


def reparse_stale(db: Session, library: Library, root: Path) -> int:
    """Reparses every visible book whose parse is missing or from an older
    parser version, then removes series left without books. Returns how
    many books were reparsed."""
    count = 0
    stale = or_(Book.parsed.is_(None), func.coalesce(Book.parsed["version"].as_string(), "") != str(PARSER_VERSION))
    books = db.scalars(select(Book).where(Book.library_id == library.id, Book.missing_since.is_(None), stale))
    for book in books:
        try:
            reparse_book(db, library, book, root)
            count += 1
        except Exception:
            logger.exception("Could not reparse book %s", book.id)
    db.flush()
    remove_empty_series(db, library)
    return count
