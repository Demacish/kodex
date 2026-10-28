"""E-book matching, book by book: ISBN first (Open Library, Google Books,
Hardcover), then title and author.

An ISBN found in the book identifies the edition directly; it is only
second-guessed when the edition's title has little in common with any
title the book goes by, or when the book's ISBNs name different books
(front pages also list the other books of a series). Without an ISBN, a candidate is
scored on title, author and year (an edition's year can differ from the
work's first publication, so the year is lenient) and goes through the
same decision rules as series: the title alone is never enough for an
automatic match.

File names often run the words together (``riversandriverboats.pdf``);
a candidate whose whole title such a name spells counts as a title match.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

from kodex.matching.config import MatchingConfig
from kodex.matching.normalize import norm
from kodex.matching.providers.base import BookRef, NotFound, ProviderError, RateLimited, RunCandidate
from kodex.matching.score import Decision, ScoredCandidate, decide, title_score

logger = logging.getLogger(__name__)

_WEIGHTS = {"title": 0.5, "author": 0.3, "year": 0.2}


@dataclass
class BookEvidence:
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    isbn: list[str] = field(default_factory=list)
    language: str | None = None
    # Every other title the book goes by: its file name (also cut at the
    # first "_", which often separates title and subtitle) and titles from
    # other sources. Only used to check a candidate's title, never searched.
    names: list[str] = field(default_factory=list)


def compact(text: str) -> str:
    """``The C++ Garden Reference`` → ``cplusplusgardenreference``: letters
    and digits only, the way a file name runs words together."""
    text = unicodedata.normalize("NFKD", text.lower().replace("+", "plus").replace("#", "sharp").replace("&", "and"))
    letters = "".join(c for c in text if c.isalnum())
    return letters[3:] if letters.startswith("the") else letters


# What may follow the title in a file name: "5thedition", "secondedition",
# "2e", "3rded", "v2", or a copy's "(1)".
_EDITION_NOTE = re.compile(
    r"(?:\d{1,2}(?:st|nd|rd|th)?(?:ed(?:ition)?|e)?"
    r"|(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)(?:ed(?:ition)?)?|v\d+)*"
)


def name_spells(title: str, names: list[str]) -> bool:
    """Whether one of the names is the whole title without its spaces,
    perhaps followed by an edition note (``…5thedition``)."""
    target = compact(title)
    if len(target) < 8:
        return False
    return any(c.startswith(target) and _EDITION_NOTE.fullmatch(c[len(target) :]) for c in map(compact, names))


def spelled_title(title: str | None, names: list[str]) -> str | None:
    """A title from elsewhere (an earlier enrichment) as far as a file name
    spells it: all of it (see ``name_spells``), or, for a name cut short,
    the words the name covers."""
    if not title:
        return None
    if name_spells(title, names):
        return title
    target = compact(title)
    for name in names:
        short = compact(name)
        if len(short) >= 20 and target.startswith(short):
            kept: list[str] = []
            for word in title.split():
                if not short.startswith(compact(" ".join([*kept, word]))):
                    break
                kept.append(word)
            if len(compact(" ".join(kept))) >= 8:
                return " ".join(kept).rstrip(":;,-–")
    return None


def _candidate(book: BookRef) -> RunCandidate:
    links = {book.provider: book.id}
    if book.work_id:
        links[f"{book.provider}_work"] = book.work_id
    for isbn in book.isbn13[:1]:
        links["isbn"] = isbn
    return RunCandidate(provider=book.provider, id=book.id, name=book.title, start_year=book.year, publisher=book.publisher,
                        format="book", language=book.language, summary=book.summary, cover_url=book.cover_url, links=links)  # fmt: skip


def author_score(ours: list[str], theirs: list[str]) -> float | None:
    if not ours or not theirs:
        return None
    best = 0.0
    for a in ours:
        for b in theirs:
            na, nb = norm(a), norm(b)
            if not na or not nb:
                continue
            # "Corey, James S. A." against "James S. A. Corey": word order free.
            best = max(best, fuzz.token_sort_ratio(na, nb) / 100)
    return best


def score_book(evidence: BookEvidence, book: BookRef) -> ScoredCandidate:
    signals: dict[str, float] = {}
    title, query, name = title_score([evidence.title], [book.title])
    if title < 1.0 and name_spells(book.title, [evidence.title, *evidence.names]):
        title, name = 1.0, book.title
    signals["title"] = title
    if (author := author_score(evidence.authors, book.authors)) is not None:
        signals["author"] = author
    if evidence.year and book.year:
        off = abs(evidence.year - book.year)
        signals["year"] = 1.0 if off <= 1 else 0.7 if off <= 3 else 0.3 if off <= 10 else 0.0
    total = sum(_WEIGHTS[k] for k in signals)
    score = sum(signals[k] * _WEIGHTS[k] for k in signals) / total
    positive = [k for k, threshold in (("author", 0.9), ("year", 0.7)) if signals.get(k, -1) >= threshold]
    return ScoredCandidate(run=_candidate(book), score=score, signals=signals, details={"title": {"query": query, "name": name},
                           "authors": book.authors}, positive=positive)  # fmt: skip


def _agreement(evidence: BookEvidence, book: BookRef) -> float:
    """How well an edition's title fits any title the book goes by."""
    if name_spells(book.title, [evidence.title, *evidence.names]):
        return 1.0
    return title_score([evidence.title, *evidence.names], [book.title])[0]


def _by_isbn(evidence: BookEvidence, clients: list[Any]) -> tuple[Decision | None, list[ScoredCandidate]]:
    """Looks up every ISBN in the book and takes the edition whose title
    fits best. Front pages that list a series' other books show up as
    editions of different books; then only a near-exact title will do,
    as it will when most of several ISBNs are unknown."""
    resolved: list[tuple[str, ScoredCandidate, float]] = []
    for isbn in evidence.isbn:
        for client in clients:
            if not hasattr(client, "lookup_isbn"):
                continue
            try:
                book = client.lookup_isbn(isbn)
            except NotFound:
                continue
            except RateLimited:
                raise
            except ProviderError as exc:
                logger.info("%s ISBN lookup failed: %s", client.name, exc)
                continue
            resolved.append((isbn, score_book(evidence, book), _agreement(evidence, book)))
            break
    if not resolved:
        return None, []
    resolved.sort(key=lambda r: r[2], reverse=True)
    isbn, best, agreement = resolved[0]
    others = [c for _, c, _ in resolved[1:] if title_score([best.run.name], [c.run.name])[0] < 0.8]
    needed = 0.9 if others or (len(evidence.isbn) >= 3 and len(resolved) == 1) else 0.5
    if agreement >= needed:
        best.positive = sorted({*best.positive, "id"})
        best.details["identified_by"] = f"ISBN {isbn}"
        return Decision("auto", best, [best], None, f"identified by ISBN {isbn}"), []
    for found_isbn, candidate, _ in resolved:
        candidate.details["isbn_names_another_title"] = found_isbn
    return None, [c for _, c, _ in resolved]


def match_book(evidence: BookEvidence, clients: list[Any], config: MatchingConfig) -> Decision:
    identified, rejected = _by_isbn(evidence, clients)
    if identified is not None:
        return identified
    found: dict[tuple[str, str], ScoredCandidate] = {}
    for client in clients:
        if not hasattr(client, "search_books"):
            continue
        author = evidence.authors[0] if evidence.authors else None
        # Title and author first; a misspelt or differently written author
        # finds nothing, so the title alone is tried next.
        for query_author in dict.fromkeys([author, None]):
            try:
                results = client.search_books(evidence.title, query_author)
            except RateLimited:
                raise
            except ProviderError as exc:
                logger.info("%s book search failed: %s", client.name, exc)
                results = []
            for book in results:
                found.setdefault((book.provider, book.id), score_book(evidence, book))
            if results:
                break
    kept = [c for c in found.values() if c.signals["title"] >= config.prefilter_ratio_min]
    decision = decide_books(kept, config)
    if rejected and decision.outcome != "auto":
        isbns = ", ".join(c.details["isbn_names_another_title"] for c in rejected)
        shown = {(c.run.provider, c.run.id) for c in decision.ranked}
        ranked = decision.ranked + [c for c in rejected if (c.run.provider, c.run.id) not in shown]
        return Decision(decision.outcome if kept else "review", decision.best or ranked[0], ranked, decision.margin,
                        f"{decision.reason}; ISBN {isbns} names another title")  # fmt: skip
    return decision


def decide_books(candidates: list[ScoredCandidate], config: MatchingConfig) -> Decision:
    """The series decision rules, except that for a book title and author
    are the match (the plan's "titel + författare"): an author agreeing
    is the one independent signal required, and the year, which e-books
    often lack, is optional. The same work at two providers (same ISBN or
    same title and authors) counts once for the margin."""
    seen: dict[tuple[str, ...], ScoredCandidate] = {}
    for candidate in sorted(candidates, key=lambda c: c.score, reverse=True):
        key = (candidate.run.links["isbn"],) if "isbn" in candidate.run.links else (
            norm(candidate.run.name), *sorted(norm(a) for a in candidate.details.get("authors", [])),
        )  # fmt: skip
        seen.setdefault(key, candidate)
    from dataclasses import replace

    from kodex.matching.score import Evidence

    decision = decide(Evidence(kind="book", titles=[], format_family="book"), list(seen.values()),
                      replace(config, min_positive_signals=1))  # fmt: skip
    if decision.outcome == "auto" and decision.best is not None and "author" not in decision.best.positive:
        return Decision("review", decision.best, decision.ranked, decision.margin, "the author doesn't match")
    return decision
