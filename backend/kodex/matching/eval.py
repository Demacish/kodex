"""Evaluation of the matching engine: precision, recall and review share
per stratum, on a frozen synthetic corpus (CI) or on a real library
(locally, see tools/eval/).

The synthetic corpus is generated from a seed, so it is the same every
run. It is built to be hard in the ways real libraries are: titles with
several runs (relaunches), namesakes with extra words ("Title Beyond"),
foreign editions of the same title and year from other publishers, TPB
lines with the same name as the issues, separate annual runs, manga with
light novels, anthologies and doujinshi of the same name, titles in
romaji, English or Japanese, e-books with and without an ISBN, and series
whose true run isn't at the provider at all (the only right answer there
is not to match automatically).

Strata: ``us_dated`` (US comics with a start year), ``us_undated``,
``tpb``, ``annual``, ``manga_romaji``, ``manga_english``, ``manga_cjk``,
``ebook_isbn``, ``ebook_title`` and ``no_true_match``.

    python -m kodex.matching.eval            # the report
    python -m kodex.matching.eval --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from rapidfuzz import fuzz

from kodex.matching.books_match import BookEvidence, match_book
from kodex.matching.config import MatchingConfig, load_config
from kodex.matching.engine import ProviderSet, Searcher
from kodex.matching.identify import ExternalRef
from kodex.matching.normalize import norm
from kodex.matching.providers.base import BookRef, IssueRef, NotFound, RunCandidate
from kodex.matching.score import Decision, Evidence

# --- Fake providers ---------------------------------------------------------------


class FakeRunProvider:
    """A provider over an in-memory world. Search returns every run sharing
    a word with the query, best WRatio first, like a real search engine's
    noisy relevance."""

    def __init__(self, name: str, runs: list[RunCandidate], issues: dict[str, list[IssueRef]]) -> None:
        self.name = name
        self.runs = {run.id: run for run in runs}
        self.issues = issues
        self.calls = 0

    def search_runs(self, query: str, **_: Any) -> list[RunCandidate]:
        self.calls += 1
        words = {w for w in norm(query).split() if len(w) >= 3} or set(norm(query).split())
        hits = [
            run for run in self.runs.values()
            if words & {w for name in (run.name, *run.aliases) for w in norm(name).split()}
        ]  # fmt: skip
        hits.sort(key=lambda r: max(fuzz.WRatio(norm(query), norm(n)) for n in (r.name, *r.aliases)), reverse=True)
        return hits[:25]

    def get_run(self, run_id: str) -> RunCandidate:
        if run_id not in self.runs:
            raise NotFound(run_id)
        return self.runs[run_id]

    def list_issues(self, run_id: str) -> list[IssueRef]:
        self.calls += 1
        return self.issues.get(run_id, [])

    def get_issue(self, issue_id: str) -> IssueRef:
        for issues in self.issues.values():
            for issue in issues:
                if issue.id == issue_id:
                    return issue
        raise NotFound(issue_id)

    def close(self) -> None:
        return None


class FakeBookProvider:
    def __init__(self, name: str, books: list[BookRef]) -> None:
        self.name = name
        self.books = books

    def lookup_isbn(self, isbn: str) -> BookRef:
        for book in self.books:
            if isbn in book.isbn13:
                return book
        raise NotFound(isbn)

    def search_books(self, title: str, author: str | None = None) -> list[BookRef]:
        words = {w for w in norm(title).split() if len(w) >= 3}
        hits = [b for b in self.books if words & set(norm(b.title).split())]
        hits.sort(key=lambda b: fuzz.WRatio(norm(title), norm(b.title)), reverse=True)
        return hits[:10]

    def close(self) -> None:
        return None


# --- The corpus ----------------------------------------------------------------------


@dataclass
class Case:
    stratum: str
    kind: str  # comics | manga | ebooks
    evidence: Evidence | None = None
    book: BookEvidence | None = None
    refs: list[ExternalRef] = field(default_factory=list)
    # (provider, id) of the right answer, or None when nothing at the
    # provider is right.
    expected: tuple[str, str] | None = None
    # Ids that count as the same answer (the run at another provider).
    equivalent: set[tuple[str, str]] = field(default_factory=set)


_WORDS = [
    "Crimson", "Silent", "Iron", "Hollow", "Neon", "Burning", "Frozen", "Hidden", "Golden", "Midnight", "Savage",
    "Broken", "Electric", "Lunar", "Wandering", "Shattered", "Velvet", "Feral", "Copper", "Amber", "Obsidian", "Scarlet",
    "Ashen", "Emerald", "Phantom", "Rusted", "Sable", "Thunder", "Winter", "Ivory",
]  # fmt: skip
_NOUNS = [
    "Harbor", "Patrol", "Circuit", "Lantern", "Kingdom", "Signal", "Orchard", "Engine", "Tide", "Compass", "Sentinel",
    "Archive", "Garden", "Frontier", "Mirror", "Atlas", "Requiem", "Beacon", "Spire", "Vanguard", "Citadel", "Meridian",
    "Covenant", "Paragon", "Outpost",
]  # fmt: skip
_PUBLISHERS = ["Northwind Comics", "Bright Harbor Press", "Atlas Lane", "Red Kite"]
# Translations, named the way real publishers of them are ("... Verlag",
# "Ediciones ...") so that matching.toml's language words recognise them.
_FOREIGN = ["Nordlicht Verlag", "Ediciones del Sur", "Editions Urbania", "Kultaranta Kiadó"]
_ROMAJI_A = [
    "Hoshi",
    "Kaze",
    "Yoru",
    "Sora",
    "Tsuki",
    "Hana",
    "Kumo",
    "Mizu",
    "Ryuu",
    "Akari",
    "Kage",
    "Yuki",
    "Hikari",
    "Umi",
]
_ROMAJI_B = ["no Kiseki", "Monogatari", "Senki", "no Uta", "Gakuen", "Tensei", "no Mori", "Days", "no Tabi", "Kitan"]
_ENGLISH_B = [
    "Miracle",
    "Tale",
    "War Chronicle",
    "Song",
    "Academy",
    "Reborn",
    "Forest",
    "Days",
    "Journey",
    "Strange Tale",
]
_KANJI_A = ["星", "風", "夜", "空", "月", "花", "雲", "水", "竜", "灯", "影", "雪", "光", "海"]
_KANJI_B = ["の奇跡", "物語", "戦記", "の歌", "学園", "転生", "の森", "デイズ", "の旅", "奇譚"]
_FIRST = ["Ada", "Bo", "Cleo", "Dag", "Esme", "Finn", "Greta", "Hugo", "Ines", "Jon", "Kaia", "Leo"]
_LAST = ["Alder", "Brook", "Corvin", "Dunmore", "Ekholm", "Falk", "Granlund", "Hale", "Ivers", "Juno"]


def _issue_list(provider: str, run_id: str, start: int, count: int, *, first: int = 1,
                per_volume: int | None = None) -> list[IssueRef]:  # fmt: skip
    return [
        IssueRef(
            provider=provider,
            id=f"{run_id}-{n}",
            run_id=run_id,
            number=str(n),
            year=start + (n - first) // 12,
            volume=str((n - first) // per_volume + 1) if per_volume else None,
        )  # fmt: skip
        for n in range(first, first + count)
    ]


_PER_VOLUME = 9  # chapters per manga volume in the synthetic world


class _World:
    def __init__(self) -> None:
        self.cv: list[RunCandidate] = []
        self.metron: list[RunCandidate] = []
        self.mangadex: list[RunCandidate] = []
        self.anilist: list[RunCandidate] = []
        self.issues: dict[str, dict[str, list[IssueRef]]] = {"comicvine": {}, "metron": {}, "mangadex": {}}
        self.books: list[BookRef] = []
        self._next = 100_000

    def nid(self) -> str:
        self._next += 1
        return str(self._next)

    def comic_run(self, name: str, start: int, publisher: str, count: int, *, fmt: str = "issue", metron: bool = True,
                  aliases: list[str] | None = None) -> RunCandidate:  # fmt: skip
        cv_id = self.nid()
        cv = RunCandidate("comicvine", cv_id, name, start_year=start, publisher=publisher, issue_count=count,
                          aliases=aliases or [], links={"comicvine": cv_id})  # fmt: skip
        self.cv.append(cv)
        self.issues["comicvine"][cv_id] = _issue_list("comicvine", cv_id, start, count)
        if metron:
            m_id = self.nid()
            mirror = RunCandidate("metron", m_id, name, start_year=start, publisher=publisher, issue_count=count, format=fmt,
                                  links={"metron": m_id, "comicvine": cv_id})  # fmt: skip
            self.metron.append(mirror)
            self.issues["metron"][m_id] = _issue_list("metron", m_id, start, count)
        return cv


def build_corpus(seed: int = 20261025) -> tuple[list[Case], ProviderSet, list[FakeBookProvider]]:
    rng = random.Random(seed)
    world = _World()
    cases: list[Case] = []
    titles = [f"{a} {b}" for a in _WORDS for b in _NOUNS]
    rng.shuffle(titles)

    def comic_family(title: str) -> dict[str, Any]:
        publisher = rng.choice(_PUBLISHERS)
        starts = sorted(rng.sample(range(1965, 2024), k=rng.choice([1, 2, 2, 3])))
        runs = [world.comic_run(title, start, publisher, rng.randint(6, 80)) for start in starts]
        tpb = world.comic_run(title, starts[-1] + 1, publisher, rng.randint(3, 9), fmt="collected")
        annual = world.comic_run(f"{title} Annual", starts[-1] + 1, publisher, rng.randint(1, 4), fmt="annual")
        if rng.random() < 0.6:
            world.comic_run(
                f"{title} {rng.choice(['Beyond', 'Legacy', 'Unlimited', 'Rebirth'])}",
                starts[-1],
                publisher,
                rng.randint(6, 40),
            )
        if rng.random() < 0.5:
            world.comic_run(
                title, starts[-1] + rng.randint(0, 2), rng.choice(_FOREIGN), rng.randint(3, 20), metron=False
            )
        return {"publisher": publisher, "runs": runs, "tpb": tpb, "annual": annual}

    def numbers_for(run: RunCandidate, k: int) -> list[str]:
        count = run.issue_count or 1
        return [str(n) for n in sorted(rng.sample(range(1, count + 1), k=min(k, count)))]

    def equivalent(run: RunCandidate) -> set[tuple[str, str]]:
        return {("metron", m.id) for m in world.metron if m.links.get("comicvine") == run.id}

    # US comics with a start year, without one, TPBs and annuals.
    for _ in range(150):
        title = titles.pop()
        family = comic_family(title)
        run = rng.choice(family["runs"])
        numbers = numbers_for(run, rng.randint(1, 10))
        years = sorted({(run.start_year or 0) + (int(n) - 1) // 12 for n in numbers})
        evidence = Evidence(kind="comic", titles=[title], start_year=run.start_year, years=years,
                            publisher=family["publisher"] if rng.random() < 0.6 else None, numbers=numbers,
                            book_count=len(numbers))  # fmt: skip
        cases.append(Case("us_dated", "comics", evidence, expected=("comicvine", run.id), equivalent=equivalent(run)))

        if len(cases) % 3 == 0:
            undated_run = rng.choice(family["runs"])
            undated = Evidence(kind="comic", titles=[title], publisher=family["publisher"] if rng.random() < 0.3 else None,
                               numbers=numbers_for(undated_run, rng.randint(1, 6)))  # fmt: skip
            cases.append(Case("us_undated", "comics", undated, expected=("comicvine", undated_run.id),
                              equivalent=equivalent(undated_run)))  # fmt: skip
        if len(cases) % 4 == 0:
            tpb = family["tpb"]
            evidence = Evidence(kind="comic", titles=[title], start_year=tpb.start_year if rng.random() < 0.7 else None,
                                years=[tpb.start_year], publisher=family["publisher"] if rng.random() < 0.5 else None,
                                format_family="collected", book_count=2)  # fmt: skip
            cases.append(Case("tpb", "comics", evidence, expected=("comicvine", tpb.id), equivalent=equivalent(tpb)))
        if len(cases) % 5 == 0:
            annual = family["annual"]
            evidence = Evidence(kind="comic", titles=[f"{title} Annual"], start_year=annual.start_year, years=[annual.start_year],
                                publisher=family["publisher"], numbers=numbers_for(annual, 1), book_count=1)  # fmt: skip
            cases.append(
                Case("annual", "comics", evidence, expected=("comicvine", annual.id), equivalent=equivalent(annual))
            )

    # Series whose true run isn't at the provider: only namesakes are.
    for _ in range(45):
        title = titles.pop()
        publisher = rng.choice(_PUBLISHERS)
        start = rng.randint(1970, 2023)
        world.comic_run(
            f"{title} {rng.choice(['Beyond', 'Legacy', 'Unlimited'])}", start, publisher, rng.randint(6, 40)
        )
        if rng.random() < 0.5:
            world.comic_run(title, start + rng.randint(8, 30), publisher, rng.randint(6, 40))
        evidence = Evidence(kind="comic", titles=[title], start_year=start, years=[start], publisher=publisher,
                            numbers=["1", "2"], book_count=2)  # fmt: skip
        cases.append(Case("no_true_match", "comics", evidence, expected=None))

    # Manga, searched by romaji, English or Japanese title.
    manga_titles = [(a, i, b, j) for i, a in enumerate(_ROMAJI_A) for j, b in enumerate(_ROMAJI_B)]
    rng.shuffle(manga_titles)
    manga_runs = []
    for index, (a, i, b, j) in enumerate(manga_titles[:130]):
        romaji, english, native = f"{a} {b}", f"The {_ENGLISH_B[j]} of {a}", f"{_KANJI_A[i]}{_KANJI_B[j]}"
        start = rng.randint(1990, 2024)
        md_id = f"md-{world.nid()}"
        al_id = world.nid()
        chapters = rng.randint(10, 200)
        md = RunCandidate("mangadex", md_id, english if rng.random() < 0.5 else romaji, start_year=start, format="manga",
                          aliases=[romaji, english, native], links={"mangadex": md_id, "anilist": al_id})  # fmt: skip
        al = RunCandidate("anilist", al_id, english, start_year=start, format="manga", aliases=[romaji, native],
                          links={"anilist": al_id})  # fmt: skip
        world.mangadex.append(md)
        world.anilist.append(al)
        world.issues["mangadex"][md_id] = _issue_list("mangadex", md_id, start, chapters, per_volume=_PER_VOLUME)
        manga_runs.append((md_id, al_id, romaji, english, native, start, chapters))
        # Same-named distractors: the light novel, an anthology, a doujinshi.
        world.anilist.append(RunCandidate("anilist", world.nid(), english, start_year=start - 1, format="novel",
                                          aliases=[romaji, native]))  # fmt: skip
        world.mangadex.append(RunCandidate("mangadex", f"md-{world.nid()}", f"{romaji} Anthology", start_year=start + 2,
                                           format="manga", aliases=[f"{native}アンソロジー"]))  # fmt: skip
        if rng.random() < 0.5:
            world.mangadex.append(RunCandidate("mangadex", f"md-{world.nid()}", f"{romaji} (Doujinshi)", start_year=start + 3,
                                               format="manga"))  # fmt: skip
        if rng.random() < 0.3:
            # Another work with exactly the same titles, years apart, that
            # only one database lists: with no year to tell them apart, the
            # only right outcome is a review.
            twin = f"md-{world.nid()}"
            world.mangadex.append(RunCandidate("mangadex", twin, md.name, start_year=start - rng.randint(6, 20), format="manga",
                                               aliases=[romaji, english, native], links={"mangadex": twin}))  # fmt: skip
            world.issues["mangadex"][twin] = _issue_list("mangadex", twin, start - 10, rng.randint(10, 200),
                                                         per_volume=_PER_VOLUME)  # fmt: skip
        stratum, query = [("manga_romaji", romaji), ("manga_english", english), ("manga_cjk", native)][index % 3]
        numbers = [str(n) for n in sorted(rng.sample(range(1, chapters + 1), k=min(rng.randint(1, 12), chapters)))]
        evidence = Evidence(kind="manga", titles=[query], start_year=start if rng.random() < 0.3 else None, numbers=numbers,
                            format_family="manga", book_count=len(numbers))  # fmt: skip
        cases.append(Case(stratum, "manga", evidence, expected=("mangadex", md_id), equivalent={("anilist", al_id)}))

    # Manga collected in volumes, the usual library layout: the files are
    # numbered by volume, and only the volumes a run's chapters are
    # collected in can be compared. (A separate generator, so the strata
    # above stay as they were.)
    vrng = random.Random(seed + 1)
    for index, (md_id, al_id, romaji, english, native, _start, chapters) in enumerate(vrng.sample(manga_runs, 40)):
        total = (chapters - 1) // _PER_VOLUME + 1
        volumes = [str(v) for v in sorted(vrng.sample(range(1, total + 1), k=vrng.randint(1, min(total, 12))))]
        evidence = Evidence(kind="manga", titles=[[romaji, english, native][index % 3]], volumes=volumes,
                            format_family="manga", book_count=len(volumes))  # fmt: skip
        cases.append(
            Case("manga_volumes", "manga", evidence, expected=("mangadex", md_id), equivalent={("anilist", al_id)})
        )

    # Hard cases with their own generator, so the strata above stay as they
    # were. A translation under the same title, start year and issue count
    # as the original (Comic Vine catalogues each); and a collected run that
    # Metron lists without its Comic Vine id, beside the issue run.
    hrng = random.Random(seed + 2)
    hard_titles = [f"{a} {b}" for a in _WORDS for b in _NOUNS if f"{a} {b}" not in titles]
    hrng.shuffle(hard_titles)
    for _ in range(30):
        title = f"The {hard_titles.pop()} Saga"
        publisher, start, count = hrng.choice(_PUBLISHERS), hrng.randint(1980, 2023), hrng.randint(6, 60)
        original = world.comic_run(title, start, publisher, count, metron=hrng.random() < 0.5)
        world.comic_run(title, start, hrng.choice(_FOREIGN), count, metron=False)
        numbers = [str(n) for n in sorted(hrng.sample(range(1, count + 1), k=min(hrng.randint(2, 8), count)))]
        evidence = Evidence(kind="comic", titles=[title], start_year=start, years=[start], numbers=numbers,
                            book_count=len(numbers))  # fmt: skip
        cases.append(Case("translated", "comics", evidence, expected=("comicvine", original.id),
                          equivalent=equivalent(original)))  # fmt: skip
    for _ in range(20):
        title = f"The {hard_titles.pop()} Chronicle"
        publisher, start = hrng.choice(_PUBLISHERS), hrng.randint(1990, 2023)
        world.comic_run(title, start, publisher, hrng.randint(12, 60))
        tpb_count = hrng.randint(2, 5)
        tpb = world.comic_run(title, start + 1, publisher, tpb_count, metron=False)
        m_id = world.nid()
        world.metron.append(RunCandidate("metron", m_id, f"{title} TPB", start_year=start + 1, publisher=publisher,
                                         issue_count=tpb_count - hrng.randint(0, 1), format="collected",
                                         links={"metron": m_id}))  # fmt: skip
        world.issues["metron"][m_id] = _issue_list("metron", m_id, start + 1, tpb_count)
        owned = [str(n) for n in range(1, hrng.randint(2, tpb_count) + 1)]
        evidence = Evidence(kind="comic", titles=[title], start_year=None, years=[start + 1], numbers=owned,
                            format_family="collected", book_count=len(owned))  # fmt: skip
        cases.append(Case("tpb_unlinked", "comics", evidence, expected=("comicvine", tpb.id),
                          equivalent={("metron", m_id)}))  # fmt: skip

    # E-books, with and without an ISBN.
    for index in range(70):
        title = f"The {titles.pop()}"
        author = f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"
        year = rng.randint(1950, 2025)
        isbn = _isbn(rng)
        book = BookRef("open_library", f"OL{world.nid()}M", title, authors=[author], year=year, isbn13=[isbn],
                       work_id=f"OL{world.nid()}W")  # fmt: skip
        world.books.append(book)
        world.books.append(BookRef("open_library", f"OL{world.nid()}M", title, authors=[f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"],
                                   year=rng.randint(1950, 2025), isbn13=[_isbn(rng)]))  # fmt: skip
        world.books.append(
            BookRef("open_library", f"OL{world.nid()}M", f"{title} Box Set", authors=[author], year=year + 5)
        )
        if index % 2:
            with_isbn = BookEvidence(title=title, authors=[author], year=year, isbn=[isbn])
            cases.append(Case("ebook_isbn", "ebooks", book=with_isbn, expected=("open_library", book.id)))
        else:
            by_title = BookEvidence(title=title, authors=[author], year=year if rng.random() < 0.8 else None)
            cases.append(Case("ebook_title", "ebooks", book=by_title, expected=("open_library", book.id)))

    providers = ProviderSet(clients={
        "comicvine": FakeRunProvider("comicvine", world.cv, world.issues["comicvine"]),  # type: ignore[dict-item]
        "metron": FakeRunProvider("metron", world.metron, world.issues["metron"]),  # type: ignore[dict-item]
        "mangadex": FakeRunProvider("mangadex", world.mangadex, world.issues["mangadex"]),  # type: ignore[dict-item]
        "anilist": FakeRunProvider("anilist", world.anilist, {}),  # type: ignore[dict-item]
    })  # fmt: skip
    return cases, providers, [FakeBookProvider("open_library", world.books)]


def _isbn(rng: random.Random) -> str:
    digits = [9, 7, 8] + [rng.randint(0, 9) for _ in range(9)]
    check = (10 - sum(d * (3 if i % 2 else 1) for i, d in enumerate(digits)) % 10) % 10
    return "".join(map(str, digits + [check]))


# --- Running and reporting -------------------------------------------------------------


@dataclass
class StratumReport:
    n: int = 0
    auto: int = 0
    auto_correct: int = 0
    review: int = 0
    none: int = 0
    answerable: int = 0
    wrong: list[dict[str, Any]] = field(default_factory=list)

    @property
    def precision(self) -> float | None:
        return self.auto_correct / self.auto if self.auto else None

    @property
    def recall(self) -> float | None:
        return self.auto_correct / self.answerable if self.answerable else None

    @property
    def review_share(self) -> float:
        return self.review / self.n if self.n else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {**{k: v for k, v in asdict(self).items() if k != "wrong"}, "precision": self.precision,
                "recall": self.recall, "review_share": self.review_share, "wrong": self.wrong[:10]}  # fmt: skip


def _correct(decision: Decision, case: Case) -> bool:
    if decision.best is None or case.expected is None:
        return False
    answers = {case.expected, *case.equivalent}
    members = decision.best.members or [decision.best.run]
    return (
        any((m.provider, m.id) in answers for m in members)
        or (decision.best.run.provider, decision.best.run.id) in answers
    )


def evaluate(
    cases: Iterable[Case], providers: ProviderSet, book_providers: list[Any], config: MatchingConfig
) -> dict[str, StratumReport]:
    searcher = Searcher(providers, config=config)
    reports: dict[str, StratumReport] = {}
    for case in cases:
        report = reports.setdefault(case.stratum, StratumReport())
        if case.book is not None:
            decision = match_book(case.book, book_providers, config)
        else:
            assert case.evidence is not None
            decision = searcher.decide(case.evidence, case.kind, refs=case.refs, book_count=case.evidence.book_count)
        report.n += 1
        report.answerable += case.expected is not None
        if decision.outcome == "auto":
            report.auto += 1
            if _correct(decision, case):
                report.auto_correct += 1
            else:
                report.wrong.append({"titles": case.evidence.titles if case.evidence else [case.book.title if case.book else ""],
                                     "expected": case.expected, "got": [decision.best.run.provider, decision.best.run.id,
                                     decision.best.run.name, decision.best.run.start_year] if decision.best else None,
                                     "reason": decision.reason})  # fmt: skip
        elif decision.outcome == "review":
            report.review += 1
        else:
            report.none += 1
    return reports


def totals(reports: dict[str, StratumReport]) -> StratumReport:
    total = StratumReport()
    for report in reports.values():
        total.n += report.n
        total.auto += report.auto
        total.auto_correct += report.auto_correct
        total.review += report.review
        total.none += report.none
        total.answerable += report.answerable
        total.wrong += report.wrong
    return total


def format_report(reports: dict[str, StratumReport]) -> str:
    def pct(value: float | None) -> str:
        return "   –  " if value is None else f"{value * 100:5.1f}%"

    lines = [f"{'stratum':<16}{'n':>5}{'auto':>6}{'right':>7}{'review':>8}{'none':>6}  precision  recall  review"]
    for name, report in [*sorted(reports.items()), ("TOTAL", totals(reports))]:
        lines.append(
            f"{name:<16}{report.n:>5}{report.auto:>6}{report.auto_correct:>7}{report.review:>8}{report.none:>6}"
            f"  {pct(report.precision):>9}  {pct(report.recall):>6}  {pct(report.review_share):>6}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the matching engine on the synthetic corpus.")
    parser.add_argument("--seed", type=int, default=20261025)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    cases, providers, books = build_corpus(args.seed)
    reports = evaluate(cases, providers, books, load_config())
    if args.json:
        print(json.dumps({name: r.as_dict() for name, r in reports.items()}, indent=1, default=str))
    else:
        print(format_report(reports))
    return 0


if __name__ == "__main__":
    sys.exit(main())
