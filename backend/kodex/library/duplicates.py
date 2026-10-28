"""The same book in two files.

- Exact duplicates have the same content id (the same pages, whatever the
  metadata in the file or the archive format). Among books whose file
  exists, every copy but the oldest book points at it with
  ``duplicate_of_id``; a mark goes away with the copy.
- Similar books are different files (another release, re-encoded pages)
  with the same number in the same series and covers within
  ``SIMILAR_COVER_DISTANCE``; they are listed for a person to decide and
  never marked.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.book import Book
from kodex.matching.covers import hamming

SIMILAR_COVER_DISTANCE = 6

_MARK = """
WITH copies AS (
    SELECT id, min(id) OVER (PARTITION BY content_id) AS first, count(*) OVER (PARTITION BY content_id) AS n
    FROM books WHERE missing_since IS NULL AND content_id IS NOT NULL
), wanted AS (
    SELECT id, CASE WHEN n > 1 AND id <> first THEN first END AS duplicate_of FROM copies
)
UPDATE books SET duplicate_of_id = wanted.duplicate_of
FROM wanted WHERE books.id = wanted.id AND books.duplicate_of_id IS DISTINCT FROM wanted.duplicate_of
"""
_CLEAR = """
UPDATE books SET duplicate_of_id = NULL
WHERE duplicate_of_id IS NOT NULL AND (missing_since IS NOT NULL OR content_id IS NULL)
"""


def mark_exact(db: Session) -> int:
    """Brings every book's ``duplicate_of_id`` up to date; returns how many
    changed."""
    changed = db.execute(text(_MARK)).rowcount + db.execute(text(_CLEAR)).rowcount  # type: ignore[attr-defined]
    db.flush()
    return int(changed)


def exact_groups(db: Session) -> list[list[int]]:
    groups: dict[int, list[int]] = defaultdict(list)
    for book_id, first in db.execute(select(Book.id, Book.duplicate_of_id).where(Book.duplicate_of_id.is_not(None))):
        if first is not None:
            groups[first].append(book_id)
    return [[first, *sorted(copies)] for first, copies in sorted(groups.items())]


def similar_groups(db: Session, max_distance: int = SIMILAR_COVER_DISTANCE) -> list[list[int]]:
    """Groups of books with the same series and number, different content
    and nearly the same cover."""
    rows = db.execute(
        select(Book.id, Book.series_id, Book.number_label, Book.content_id, Book.cover_phash).where(
            Book.missing_since.is_(None), Book.cover_phash.is_not(None), Book.series_id.is_not(None),
            Book.number_label.is_not(None), Book.duplicate_of_id.is_(None),
        )
    ).all()  # fmt: skip
    by_number: dict[tuple[Any, Any], list[Any]] = defaultdict(list)
    for row in rows:
        by_number[(row.series_id, row.number_label)].append(row)
    groups = []
    for candidates in by_number.values():
        if len(candidates) < 2:
            continue
        parent = {row.id: row.id for row in candidates}

        def root(book_id: int, parent: dict[int, int] = parent) -> int:
            while parent[book_id] != book_id:
                book_id = parent[book_id]
            return book_id

        for i, a in enumerate(candidates):
            for b in candidates[i + 1 :]:
                if a.content_id != b.content_id and hamming(a.cover_phash, b.cover_phash) <= max_distance:
                    parent[root(b.id)] = root(a.id)
        members: dict[int, list[int]] = defaultdict(list)
        for row in candidates:
            members[root(row.id)].append(row.id)
        groups += [sorted(ids) for ids in members.values() if len(ids) > 1]
    return sorted(groups)
