"""Where a reader is in a book: a native locator, in the kind of the
reader that made it, plus the progression (``progress_percent``), which
every reader understands. Readers don't translate each other's locators:
one that gets a kind it can't use opens at the progression instead.

Kinds:

- ``page``: a 0-based page index (comics and image folders; the web's
  image reader, v1's reader);
- ``pdf``: a 1-based PDF page number (pdf.js, v1);
- ``cfi``: an EPUB CFI (foliate-js; epub.js in v1);
- ``xpointer``: KOReader's position in an EPUB;
- ``kobo``: a Kobo e-reader's location in a KEPUB;
- ``other``: a position of another shape from v1's clients, kept as it
  came for the reader that made it;
- ``percent``: only the progression is known.

Page numbers are the one translation: a KOReader page is a page index plus
one, for paged formats only.
"""

from __future__ import annotations

from typing import Literal

from app.models.book import Book
from app.models.enums import PAGE_BASED_FORMATS, BookFormat

LocatorKind = Literal["page", "pdf", "cfi", "xpointer", "kobo", "other", "percent"]
KINDS: tuple[LocatorKind, ...] = ("page", "pdf", "cfi", "xpointer", "kobo", "other", "percent")
# v1 stored a position known only as a fraction like this.
_V1_PERCENT = "percent:"
MAX_LENGTH = 512


def infer(book: Book, position: str | None) -> LocatorKind | None:
    """The kind of a position sent without one (v1's clients)."""
    if position is None:
        return None
    if position.startswith(_V1_PERCENT):
        return "percent"
    if book.file_format == BookFormat.EPUB:
        return "cfi" if position.startswith("epubcfi(") else "xpointer" if position.startswith("/") else "other"
    if not position.isdigit():
        return "other"
    return "pdf" if book.file_format == BookFormat.PDF else "page"


def normalize(book: Book, kind: str | None, position: str | None) -> tuple[LocatorKind | None, str | None]:
    """A reported position with its kind (inferred when missing); a
    position known only by its progression has no locator."""
    found: LocatorKind | None = next((k for k in KINDS if k == kind), None) or infer(book, position)
    if position is None or found is None or found == "percent":
        return ("percent" if found else None), None
    return found, position[:MAX_LENGTH]


def paged(book: Book) -> bool:
    return book.file_format == BookFormat.PDF or book.file_format in PAGE_BASED_FORMATS


def page_index(book: Book, kind: str | None, position: str | None, percent: float) -> int | None:
    """The 0-based page a position points at, for paged formats."""
    if not paged(book):
        return None
    if position is not None and position.isdigit():
        if kind == "page":
            return int(position)
        if kind == "pdf":
            return max(int(position) - 1, 0)
    if book.page_count:
        return min(int(percent / 100 * book.page_count), book.page_count - 1)
    return None


def to_koreader(book: Book, kind: str | None, position: str | None, percent: float) -> str | None:
    """A position as KOReader's ``progress``: a 1-based page for paged
    formats, its own XPointer for an EPUB; None when there is none."""
    if paged(book):
        index = page_index(book, kind, position, percent)
        return None if index is None else str(index + 1)
    return position if kind == "xpointer" else None


def from_koreader(book: Book, progress: str | None, percentage: float) -> tuple[LocatorKind, str | None]:
    """KOReader's ``progress`` as this book's kind and position."""
    if progress is not None and paged(book) and progress.isdigit():
        page = max(int(progress), 1)
        return ("pdf", str(page)) if book.file_format == BookFormat.PDF else ("page", str(page - 1))
    if progress is not None and not paged(book) and progress.startswith("/") and len(progress) <= MAX_LENGTH:
        return "xpointer", progress
    return "percent", None
