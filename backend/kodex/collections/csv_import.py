"""C14 — CSV pull-list/collection import (League of Comic Geeks, Goodreads)
→ fuzzy-match against the local library → a new manual Collection.

Real sample exports from either service were not available when this was
written — see claude/omnibus-och-ai-forbattringar.md's open questions.
Column detection is deliberately lenient (a set of common header-name
aliases, case-insensitive) rather than hardcoded exact column names, so a
close-enough real export still works; this should still be verified
against a real LOCG/Goodreads export before relying on it.

Fuzzy matching reuses app/ai/collections.py's own choice: difflib
(stdlib, no new dependency) rather than adding rapidfuzz — see that
module's docstring for the same reasoning, which applies identically here.
"""

from __future__ import annotations

import csv
import difflib
import io
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models.book import Book
from app.models.series import Series

_TITLE_ALIASES = {"title", "series", "series title", "series_title", "book title", "name", "comic"}
_AUTHOR_ALIASES = {"author", "authors", "author l-f", "writer"}
_ISSUE_ALIASES = {"issue", "issue number", "issue_number", "number", "#", "vol"}

AUTO_MATCH_THRESHOLD = 0.85
REVIEW_THRESHOLD = 0.70


class CsvImportError(Exception):
    pass


@dataclass
class ImportRow:
    row_index: int
    raw_title: str
    raw_author: str | None
    raw_issue_number: str | None
    # "matched" (score >= AUTO_MATCH_THRESHOLD), "needs_review" (>= REVIEW_
    # THRESHOLD), or "unmatched" — see bucket_rows below.
    bucket: str
    score: float
    matched_series_id: int | None
    matched_series_title: str | None
    # Every book this row resolves to once accepted — a whole series when
    # no issue number narrowed it down, one book when it did.
    book_ids: list[int] = field(default_factory=list)


def _find_column(fieldnames: Sequence[str], aliases: set[str]) -> str | None:
    lowered = {f.strip().lower(): f for f in fieldnames}
    for alias in aliases:
        if alias in lowered:
            return lowered[alias]
    return None


def parse_csv(content: bytes) -> list[dict[str, Any]]:
    """format ("locg"/"goodreads") isn't actually branched on here — both
    reduce to "a title column, optionally an author and/or issue number
    column" once you're lenient about header names (see this module's
    docstring), so one lenient parser covers both rather than two near-
    identical hardcoded ones.
    """
    try:
        text = content.decode("utf-8-sig")  # -sig strips a BOM, common in Excel-exported CSVs
    except UnicodeDecodeError as exc:
        raise CsvImportError(f"Could not decode CSV as UTF-8: {exc}") from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise CsvImportError("CSV has no header row")

    title_col = _find_column(reader.fieldnames, _TITLE_ALIASES)
    if title_col is None:
        raise CsvImportError(f"Could not find a title/series column among: {reader.fieldnames}")
    author_col = _find_column(reader.fieldnames, _AUTHOR_ALIASES)
    issue_col = _find_column(reader.fieldnames, _ISSUE_ALIASES)

    rows: list[dict[str, Any]] = []
    for raw_row in reader:
        title = (raw_row.get(title_col) or "").strip()
        if not title:
            continue
        rows.append(
            {
                "title": title,
                "author": ((raw_row.get(author_col) or "").strip() or None) if author_col else None,
                "issue_number": ((raw_row.get(issue_col) or "").strip() or None) if issue_col else None,
            }
        )
    return rows


def _best_series_match(title: str, series_rows: Sequence[tuple[int, str]]) -> tuple[int, str, float] | None:
    target = title.strip().lower()
    best: tuple[int, str, float] | None = None
    for series_id, series_title in series_rows:
        score = difflib.SequenceMatcher(None, target, series_title.strip().lower()).ratio()
        if best is None or score > best[2]:
            best = (series_id, series_title, score)
    return best


def match_rows(db: Session, rows: Sequence[dict[str, Any]]) -> list[ImportRow]:
    series_rows = [(series_id, title) for series_id, title in db.query(Series.id, Series.title).all()]
    results: list[ImportRow] = []

    for index, row in enumerate(rows):
        match = _best_series_match(row["title"], series_rows)
        score = match[2] if match else 0.0
        bucket = (
            "matched" if score >= AUTO_MATCH_THRESHOLD else "needs_review" if score >= REVIEW_THRESHOLD else "unmatched"
        )

        book_ids: list[int] = []
        series_id = match[0] if match and bucket != "unmatched" else None
        series_title = match[1] if match and bucket != "unmatched" else None

        if series_id is not None:
            series_books = db.query(Book.id, Book.number).filter(Book.series_id == series_id).all()
            if row["issue_number"]:
                book_ids = [book_id for book_id, number in series_books if _issue_matches(row["issue_number"], number)]
            if not book_ids:
                # No issue number given, or it didn't match a specific
                # book — fall back to the whole series: "I have this
                # series on my pull list" reasonably means every issue
                # you already own, not none of them.
                book_ids = [book_id for book_id, _number in series_books]

        results.append(
            ImportRow(
                row_index=index,
                raw_title=row["title"],
                raw_author=row["author"],
                raw_issue_number=row["issue_number"],
                bucket=bucket,
                score=round(score, 3),
                matched_series_id=series_id,
                matched_series_title=series_title,
                book_ids=book_ids,
            )
        )
    return results


def _issue_matches(raw_issue_number: str, book_number: float | None) -> bool:
    if book_number is None:
        return False
    try:
        return float(raw_issue_number.lstrip("#")) == book_number
    except ValueError:
        return False
