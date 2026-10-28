"""kodex.formats.pdf and the e-book evidence built from it."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.enums import BookFormat, MetadataSource
from kodex.formats.embedded import read_embedded
from kodex.formats.pdf import isbns_in_text, read_pdf, split_authors, usable_title
from kodex.matching.books_match import spelled_title
from kodex.matching.engine import book_evidence
from tests.pdf_helpers import write_text_pdf


def test_read_pdf_title_authors_and_isbn_from_the_copyright_page(tmp_path):
    path = write_text_pdf(
        tmp_path / "lanternatlas.pdf",
        ["The Lantern Atlas", "Copyright 2021. ISBN: 978-0-30640-100-8 [LSI]", "Chapter 1"],
        title="The Lantern Atlas",
        author="Ada Alder II and Bo Brook",
    )
    assert read_pdf(path) == {
        "title": "The Lantern Atlas",
        "authors": ["Ada Alder II", "Bo Brook"],
        "isbn": ["9780306401008"],
    }
    assert read_embedded(path, BookFormat.PDF) == {"pdf": read_pdf(path)}


def test_read_pdf_leaves_out_authoring_tool_leftovers(tmp_path):
    path = write_text_pdf(tmp_path / "harbour.pdf", ["Harbour Lights"], title="harbour_fm.indd", author="Sys")
    assert read_pdf(path) == {}
    assert read_embedded(path, BookFormat.PDF) == {}


def test_isbns_past_the_front_pages_are_ignored(tmp_path):
    pages = ["Title"] + ["text"] * 8 + ["Also available: ISBN 978-0-30640-900-4"]
    assert read_pdf(write_text_pdf(tmp_path / "ads.pdf", pages)) == {}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ISBN 978-0-30640-700-0", ["9780306407000"]),
        ("ISBN-13: 978-0-30640-900-4\nISBN-10: 0-306-40900-3", ["9780306409004"]),
        ("eISBN: 978 0 30640 800 7 (ebook)", ["9780306408007"]),
        ("ISBN (paperback): 0-306-40615-2", ["9780306406157"]),
        ("ISBN 978-0-30640-700-5", []),  # bad check digit
        ("Order number 978-0-30640-700-0", []),  # no label
    ],
)
def test_isbns_in_text(text, expected):
    assert isbns_in_text(text) == expected


def test_usable_title_and_split_authors():
    assert usable_title("Microsoft Word - Garden Notes") == "Garden Notes"
    assert usable_title("Untitled") is None
    assert usable_title("978-1-23") is None
    assert split_authors("A. Alder/ B. Jane Brook") == ["A. Alder", "B. Jane Brook"]
    assert split_authors("Corey, James S. A.") == ["Corey, James S. A."]
    assert split_authors("Ada Alder, Bo Brook") == ["Ada Alder", "Bo Brook"]
    assert split_authors("Administrator") == []


@pytest.mark.parametrize(
    ("title", "names", "expected"),
    [
        ("Rivers and River Boats", ["riversandriverboats"], "Rivers and River Boats"),
        ("C++ Garden Reference", ["cplusplusgardenreference (1)"], "C++ Garden Reference"),
        ("The Quiet Harbour Handbook", ["quietharbourhandbook5thedition"], "The Quiet Harbour Handbook"),
        ("Lantern Atlas: A Complete Guide to Charting Coasts, Rivers, and Lakes",
         ["lanternatlas_acompleteguidetochartingcoastsriversan"],
         "Lantern Atlas: A Complete Guide to Charting Coasts, Rivers"),
        ("River Cookbook", ["riversandriverboats"], None),
        ("Rivers", ["riversboats"], None),  # too short to say
        ("Garden", ["gardenanintrotopruningsecondedition"], None),
        ("Harbour Go", ["harbourgo3e"], "Harbour Go"),
        ("Harbourage", ["harbouragego"], None),  # "go" is no edition note
        ("Garden Pocket", ["Garden Pocket Reference"], None),
    ],
)  # fmt: skip
def test_spelled_title(title, names, expected):
    assert spelled_title(title, names) == expected


def _book(file_path, source, raw=None, **meta):
    fields = {"title": None, "authors": [], "isbn": None, "published_year": None, "language": None, **meta}
    return SimpleNamespace(
        file_path=file_path, parsed={"title": file_path.rsplit("/", 1)[-1].removesuffix(".pdf")},
        book_metadata=SimpleNamespace(source=source, raw=raw, **fields),
    )  # fmt: skip


def test_book_evidence_prefers_the_pdf_over_an_enrichment():
    book = _book("a/lanternkeys.pdf", MetadataSource.ENRICHED,
                 raw={"pdf": {"title": "Lantern Keys", "authors": ["Ödön Älvsjö"],
                              "isbn": ["9780306402005"]}},
                 title="Something Else", authors=["Someone"], isbn="9780306406157")  # fmt: skip
    evidence = book_evidence(book)
    assert (evidence.title, evidence.authors, evidence.isbn) == (
        "Lantern Keys",
        ["Ödön Älvsjö"],
        ["9780306402005"],
    )


def test_book_evidence_uses_an_enrichment_only_as_far_as_the_name_spells_it():
    spelled = _book("a/riversandriverboats.pdf", MetadataSource.ENRICHED, title="Rivers and River Boats",
                    authors=["Bo Brook"], published_year=2018)  # fmt: skip
    evidence = book_evidence(spelled)
    assert (evidence.title, evidence.authors, evidence.year) == ("Rivers and River Boats", [], None)
    assert evidence.names == ["riversandriverboats"]
    other = _book("a/riversandriverboats.pdf", MetadataSource.ENRICHED, title="River Cookbook")
    assert book_evidence(other).title == "riversandriverboats"


def test_book_evidence_puts_the_file_before_a_person_and_filters_scanned_leftovers():
    manual = _book("a/x_y.pdf", MetadataSource.MANUAL, raw={"pdf": {"title": "From The File"}},
                   title="Chosen Title", authors=["A Person"])  # fmt: skip
    evidence = book_evidence(manual)
    assert (evidence.title, evidence.authors) == ("From The File", ["A Person"])
    assert evidence.names == ["Chosen Title", "x_y", "x"]
    scanned = _book("a/harbour.pdf", MetadataSource.EMBEDDED, title="harbour_fm.indd", authors=["Sys"])
    assert (book_evidence(scanned).title, book_evidence(scanned).authors) == ("harbour", [])
