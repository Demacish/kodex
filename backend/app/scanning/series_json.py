"""B9 — "self-describing library": a `series.json` companion file written
into a series' own folder, capturing everything needed to restore that
series' metadata without a single provider (Comic Vine/AniList/Open
Library/Google Books) call. The recovery story this exists for: the
database is lost/corrupted, the library folders on disk are not — a
rescan alone only recreates bare Book/Series rows from the files
themselves (embedded ComicInfo.xml/OPF at best); importing every
series.json afterwards restores enrichment results, manual edits, and
external ids on top of that, with zero network calls.

Deliberately standalone from app/scanning/scanner.py's own scan pipeline
(no shared internal upsert functions) — scanner.py is the battle-tested,
carefully-evolved path for *discovering* books from files, with its own
edition-type/number-fallback classification logic already covered
elsewhere (see claude/forbattringar-serier-samlingar.md sections B/C).
series.json import only ever updates the BookMetadata/Book.number/
Book.edition_type of a Book row that scanning has *already* created —
it never discovers new files or creates Book rows — so it doesn't need
(and shouldn't risk touching) any of that machinery.

Not covered by this file: cover images. BookMetadata.cover_path points
into settings.covers_dir, a separate storage location from the library
folders this module reads/writes — out of scope for "restore from what's
still on the library disk"; a re-enrichment pass (or a manual match) will
refetch covers for a book restored via this path.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.book import Book
from app.models.enums import BookEditionType
from app.models.library import Library
from app.models.metadata import BookMetadata
from app.models.series import Series

logger = logging.getLogger(__name__)

SERIES_JSON_VERSION = 1
SERIES_JSON_FILENAME = "series.json"

_METADATA_FIELDS = (
    "title",
    "sort_title",
    "authors",
    "genres",
    "tags",
    "story_arcs",
    "story_arc_numbers",
    "summary",
    "publisher",
    "published_year",
    "language",
    "isbn",
    "external_ids",
)


def _series_folder(library: Library, series: Series, *, libraries_root: Path) -> Path | None:
    """The series' own folder, derived from the common parent of its
    books' file_paths (scanner.py's one-folder-one-series convention) —
    not Series.path, which is cosmetic/cover-computed and not guaranteed
    to still match the real folder after e.g. a Comic Vine reparent (see
    Series.path's own docstring). None for a series with no books at all
    (nothing to export) or one whose books don't share a single parent
    folder (defensive — not expected under the normal scan convention).
    """
    if not series.books:
        return None
    parents = {Path(book.file_path).parent for book in series.books}
    if len(parents) != 1:
        logger.warning("Series %s's books don't share one folder — skipping series.json export", series.id)
        return None
    return libraries_root / library.path / next(iter(parents))


def export_series(series: Series, *, libraries_root: Path) -> Path | None:
    """Writes/overwrites series.json in the series' own folder. Returns
    the path written, or None if there was nothing to export (see
    _series_folder). Caller is responsible for stamping
    Series.metadata_exported_at and committing.
    """
    folder = _series_folder(series.library, series, libraries_root=libraries_root)
    if folder is None:
        return None

    data = {
        "kodex_series_json_version": SERIES_JSON_VERSION,
        "exported_at": dt.datetime.now(dt.UTC).isoformat(),
        "series": {
            "title": series.title,
            "sort_title": series.sort_title,
            "comicvine_volume_id": series.comicvine_volume_id,
        },
        "books": [
            {
                "file_path": book.file_path,
                "number": book.number,
                "edition_type": book.edition_type.value,
                "metadata": (
                    {field: getattr(book.book_metadata, field) for field in _METADATA_FIELDS}
                    if book.book_metadata is not None
                    else None
                ),
            }
            for book in series.books
        ],
    }

    # Mylar3's block alongside Kodex's own keys: one file for both readers.
    from kodex.formats.series_json import merge, mylar_metadata

    first_with_meta = next((b.book_metadata for b in series.books if b.book_metadata is not None), None)
    data = merge(data, mylar_metadata(
        name=series.title, comicvine_id=series.comicvine_volume_id, start_year=series.start_year,
        publisher=series.publisher or (first_with_meta.publisher if first_with_meta else None),
        summary=series.summary, format_family=series.format_family, status=series.status,
        book_count=len(series.books),
    ))  # fmt: skip

    folder.mkdir(parents=True, exist_ok=True)
    path = folder / SERIES_JSON_FILENAME
    partial = path.with_name(path.name + ".part")
    partial.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    partial.replace(path)
    return path


def import_series_json_file(db: Session, library: Library, path: Path) -> dict:
    """Restores BookMetadata (+ Book.number/edition_type) for every book
    entry in one series.json whose file_path matches an existing Book row
    in this library — books not already known to the database (a file
    that hasn't been scanned yet) are counted as "not found", never
    created here (see this module's own docstring for why). Returns
    counts, never raises on a per-book mismatch — one bad entry in a
    hand-edited series.json must not abort the rest of the file, same
    "isolate failures per-item" principle as app/workers/tasks.py's
    library-wide jobs.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return {"path": str(path), "updated": 0, "not_found": 0, "error": str(exc)}

    updated = 0
    not_found = 0
    for entry in data.get("books", []):
        file_path = entry.get("file_path")
        if not file_path:
            continue
        book = db.query(Book).filter(Book.library_id == library.id, Book.file_path == file_path).one_or_none()
        if book is None:
            not_found += 1
            continue

        if entry.get("number") is not None:
            book.number = entry["number"]
        if entry.get("edition_type"):
            try:
                book.edition_type = BookEditionType(entry["edition_type"])
            except ValueError:
                pass  # a hand-edited/foreign series.json with a bad value — skip just this field, not the whole book

        meta_fields = entry.get("metadata")
        if meta_fields:
            meta = book.book_metadata
            if meta is None:
                meta = BookMetadata(
                    book_id=book.id, title=meta_fields.get("title") or Path(file_path).stem, sort_title=""
                )
                book.book_metadata = meta
            for field in _METADATA_FIELDS:
                if field in meta_fields and meta_fields[field] not in (None, "", []):
                    setattr(meta, field, meta_fields[field])
            db.add(meta)

        db.add(book)
        updated += 1

    db.commit()
    return {"path": str(path), "updated": updated, "not_found": not_found}


def import_library_series_json(db: Session, library: Library, *, libraries_root: Path) -> list[dict]:
    """Walks every series.json under this library's folder and restores
    each in turn — the counterpart to /libraries/{id}/scan, run after a
    rescan to layer restored metadata back on top of the bare Book rows
    scanning alone produces.
    """
    library_root = libraries_root / library.path
    results = []
    for path in sorted(library_root.rglob(SERIES_JSON_FILENAME)):
        results.append(import_series_json_file(db, library, path))
    return results
