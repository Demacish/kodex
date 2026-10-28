"""kodex.matching.books_match: ISBN first, then title, author and year."""

from __future__ import annotations

from kodex.matching.books_match import BookEvidence, author_score, match_book
from kodex.matching.config import load_config
from kodex.matching.providers.base import BookRef, NotFound

CONFIG = load_config()


class FakeBooks:
    name = "fake"

    def __init__(self, by_isbn=None, results=None):
        self.by_isbn = by_isbn or {}
        self.results = results or []

    def lookup_isbn(self, isbn):
        if isbn not in self.by_isbn:
            raise NotFound(isbn)
        return self.by_isbn[isbn]

    def search_books(self, title, author=None):
        return self.results


def _book(bid, title, authors, year, isbn=None):
    return BookRef(
        provider="open_library", id=bid, title=title, authors=authors, year=year, isbn13=[isbn] if isbn else []
    )


def test_isbn_identifies_the_edition():
    edition = _book("OL1M", "The Crimson Orchard", ["Ada Alder"], 2011, "9780306406157")
    decision = match_book(
        BookEvidence("The Crimson Orchard", ["Ada Alder"], isbn=["9780306406157"]),
        [FakeBooks({"9780306406157": edition})],
        CONFIG,
    )
    assert decision.outcome == "auto" and decision.best.run.id == "OL1M"
    assert decision.best.run.links["isbn"] == "9780306406157"


def test_an_isbn_for_another_title_goes_to_review():
    edition = _book("OL2M", "A Cookbook of Soups", ["Someone"], 2001, "9780306406157")
    decision = match_book(
        BookEvidence("The Crimson Orchard", isbn=["9780306406157"]), [FakeBooks({"9780306406157": edition})], CONFIG
    )
    assert decision.outcome == "review"


def test_title_and_author_without_isbn():
    results = [
        _book("W1", "The Crimson Orchard", ["Ada Alder"], 2011),
        _book("W2", "The Crimson Orchard Cookbook", ["Bo Brook"], 2015),
    ]
    decision = match_book(
        BookEvidence("The Crimson Orchard", ["Alder, Ada"], year=2011), [FakeBooks(results=results)], CONFIG
    )
    assert decision.outcome == "auto", decision.reason
    assert decision.best.run.id == "W1"


def test_title_and_author_are_enough_without_a_year():
    results = [_book("W1", "Lantern Pocket Guide", ["Cleo Cedar"], 2013)]
    decision = match_book(BookEvidence("Lantern Pocket Guide", ["Cleo Cedar"]), [FakeBooks(results=results)], CONFIG)
    assert decision.outcome == "auto", decision.reason


def test_search_falls_back_to_the_title_alone():
    class TitleOnly(FakeBooks):
        def search_books(self, title, author=None):
            return [] if author else [_book("W1", "Lantern Pocket Guide", ["Cleo Cedar"], 2013)]

    decision = match_book(BookEvidence("Lantern Pocket Guide", ["Cedar, Cleo"]), [TitleOnly()], CONFIG)
    assert decision.best is not None and decision.best.run.id == "W1"


def test_title_alone_is_not_enough():
    decision = match_book(
        BookEvidence("The Crimson Orchard"),
        [FakeBooks(results=[_book("W1", "The Crimson Orchard", ["Ada Alder"], 2011)])],
        CONFIG,
    )
    assert decision.outcome == "review"


def test_author_score_ignores_word_order():
    assert author_score(["Corey, James S. A."], ["James S. A. Corey"]) == 1.0
    assert author_score([], ["x"]) is None


def test_a_series_siblings_isbn_is_passed_over_for_the_books_own():
    sibling = _book("OL3M", "Harbour Pilot+ Exam Guide", ["Dag Dune"], 2022, "9780306403002")
    own = _book("OL4M", "Harbour Crew+ Exam Guide", ["Dag Dune"], 2022, "9780306404009")
    decision = match_book(
        BookEvidence("Books in the Exam Guide Series", isbn=["9780306403002", "9780306404009"],
                     names=["harbourcrewplusexamguide_preparepractice", "harbourcrewplusexamguide"]),
        [FakeBooks({"9780306403002": sibling, "9780306404009": own})],
        CONFIG,
    )  # fmt: skip
    assert decision.outcome == "auto" and decision.best.run.id == "OL4M"


def test_a_rejected_isbn_stays_a_candidate_for_review():
    other = _book("OL2M", "A Cookbook of Soups", ["Someone"], 2001, "9780306406157")
    decision = match_book(
        BookEvidence("The Crimson Orchard", isbn=["9780306406157"]),
        [FakeBooks({"9780306406157": other}, results=[_book("W1", "The Crimson Orchard", ["Ada Alder"], 2011)])],
        CONFIG,
    )
    assert decision.outcome == "review"
    assert [c.run.id for c in decision.ranked] == ["W1", "OL2M"]
    assert "9780306406157 names another title" in decision.reason


def test_a_file_name_that_spells_the_title_is_a_title_match():
    edition = _book("OL5M", "The Harbour Survey Method", ["Eli Elm"], 2010, "9780306405006")
    decision = match_book(
        BookEvidence("harboursurveymethod_aprovenapproachforchartingcoasts", isbn=["9780306405006"],
                     names=["harboursurveymethod"]),
        [FakeBooks({"9780306405006": edition})],
        CONFIG,
    )  # fmt: skip
    assert decision.outcome == "auto" and decision.best.signals["title"] == 1.0


def test_isbns_of_different_books_need_a_near_exact_title():
    first = _book("OL6M", "Harbour Pilot+ Exam Guide", ["Dag Dune"], 2022, "9780306403002")
    second = _book("OL7M", "Harbour Signals+ Exam Guide", ["Dag Dune"], 2022, "9780306404009")
    decision = match_book(
        BookEvidence("Harbour Crew+ Exam Guide", isbn=["9780306403002", "9780306404009"]),
        [FakeBooks({"9780306403002": first, "9780306404009": second})],
        CONFIG,
    )
    assert decision.outcome == "review"
    assert {c.run.id for c in decision.ranked} == {"OL6M", "OL7M"}


def test_the_main_title_can_be_the_spelling_file_name():
    edition = _book("OL8M", "C++20 Garden Cookbook", ["Fay Fern"], 2022, "9780306401008")
    decision = match_book(
        BookEvidence("cplusplus20gardencookbook", isbn=["9780306401008"]),
        [FakeBooks({"9780306401008": edition})],
        CONFIG,
    )
    assert decision.outcome == "auto" and decision.best.signals["title"] == 1.0
