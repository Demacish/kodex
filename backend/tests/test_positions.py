"""kodex.reading.positions: kinds of locators, inferred for v1's clients,
and the one translation there is (KOReader pages)."""

from __future__ import annotations

import pytest

from app.models.book import Book
from app.models.enums import BookFormat
from kodex.reading import positions


def _book(fmt: BookFormat, pages: int | None = 40) -> Book:
    return Book(file_path=f"a.{fmt.value}", file_format=fmt, page_count=pages)


@pytest.mark.parametrize(
    ("fmt", "position", "kind"),
    [
        (BookFormat.CBZ, "12", "page"),
        (BookFormat.PDF, "12", "pdf"),
        (BookFormat.EPUB, "epubcfi(/6/4!/4/2:0)", "cfi"),
        (BookFormat.EPUB, "/body/DocFragment[3]/body/p[2]/text().0", "xpointer"),
        (BookFormat.EPUB, "percent:0.420000", "percent"),
        (BookFormat.CBZ, "chapter-2", "other"),
        (BookFormat.EPUB, "chapter-2", "other"),
        (BookFormat.CBZ, None, None),
    ],
)
def test_v1_positions_get_their_kind(fmt, position, kind):
    assert positions.infer(_book(fmt), position) == kind


def test_a_position_known_only_by_progression_has_no_locator():
    book = _book(BookFormat.EPUB, None)
    assert positions.normalize(book, None, "percent:0.5") == ("percent", None)
    assert positions.normalize(book, "cfi", None) == ("percent", None)
    assert positions.normalize(book, None, None) == (None, None)
    assert positions.normalize(book, "made-up", "epubcfi(/6/4)") == ("cfi", "epubcfi(/6/4)")


@pytest.mark.parametrize(
    ("fmt", "kind", "position", "percent", "koreader"),
    [
        (BookFormat.CBZ, "page", "9", 25.0, "10"),
        (BookFormat.PDF, "pdf", "50", 25.0, "50"),
        (BookFormat.CBZ, "percent", None, 50.0, "21"),
        (BookFormat.CBZ, "percent", None, 100.0, "40"),
        (BookFormat.EPUB, "xpointer", "/body/p[1]", 10.0, "/body/p[1]"),
        (BookFormat.EPUB, "cfi", "epubcfi(/6/4)", 10.0, None),
    ],
)
def test_positions_for_koreader(fmt, kind, position, percent, koreader):
    assert positions.to_koreader(_book(fmt), kind, position, percent) == koreader


@pytest.mark.parametrize(
    ("fmt", "progress", "expected"),
    [
        (BookFormat.CBZ, "11", ("page", "10")),
        (BookFormat.PDF, "11", ("pdf", "11")),
        (BookFormat.CBZ, "0", ("page", "0")),
        (BookFormat.EPUB, "/body/DocFragment[2]/body/p[1]/text().4", ("xpointer", "/body/DocFragment[2]/body/p[1]/text().4")),
        (BookFormat.EPUB, "/" + "x" * 600, ("percent", None)),
        (BookFormat.CBZ, None, ("percent", None)),
    ],
)  # fmt: skip
def test_positions_from_koreader(fmt, progress, expected):
    assert positions.from_koreader(_book(fmt), progress, 0.3) == expected


def test_pages_left_count_from_any_kind():
    book = _book(BookFormat.CBZ, 40)
    assert positions.page_index(book, "page", "9", 0) == 9
    assert positions.page_index(_book(BookFormat.PDF, 40), "pdf", "10", 0) == 9
    assert positions.page_index(book, "xpointer", None, 50.0) == 20
    assert positions.page_index(_book(BookFormat.EPUB, None), "cfi", "epubcfi(/6/4)", 50.0) is None
