"""The matching pipeline for one series, as the plan lays it out:

1. **Evidence** from every book: titles (ComicInfo, MetronInfo, parsed
   names, the folder), the start year, the books' years, publisher,
   numbers, page counts, and external ids found by ``identify``.
2. **Id resolution**: a Comic Vine or Metron id that most books agree on
   identifies the run without searching.
3. **Aliases** before the network: a positive alias gives a candidate
   (still scored), a negative one rules a candidate out.
4. **Search** the providers for the library type, keep candidates whose
   title passes the cheap local prefilter, fetch issue lists for the best
   few, and compare covers for the top three while the decision is still
   open.
5. **Decide** (``kodex.matching.score``) and **apply**: external ids,
   empty unlocked fields, issue ids per book (unresolved numbers are
   flagged), all logged in the review queue, where an automatic decision
   can be reverted.

Nothing here runs at import time or needs the network in tests:
providers come from a :class:`ProviderSet`, which tests build on replay
transports.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.models.book import Book
from app.models.enums import MetadataSource
from app.models.library import Library
from app.models.metadata import BookMetadata
from app.models.series import Series
from kodex.core import outbound
from kodex.matching.config import MatchingConfig, get_config
from kodex.matching.covers import best_distance, book_cover_page, hashes_from_bytes, same_artwork
from kodex.matching.identify import ExternalRef, identify
from kodex.matching.models import MatchReview, SeriesAlias, SeriesExternalId
from kodex.matching.normalize import norm
from kodex.matching.parse import parse_folder
from kodex.matching.providers.base import (
    ClientSettings,
    IssueRef,
    NotConfigured,
    NotFound,
    ProviderClient,
    ProviderError,
    RateLimited,
    RunCandidate,
)
from kodex.matching.score import Decision, Evidence, ScoredCandidate, decide, merge_linked, score_candidate, title_score
from kodex.matching.series_ops import remember_alias

logger = logging.getLogger(__name__)

# The series fields matching may fill in when they are empty and unlocked.
SERIES_FIELDS = ("publisher", "start_year", "summary", "status")
_KIND_BY_LIBRARY = {"comics": "comics", "manga": "manga", "ebooks": "ebooks"}


# --- Providers ----------------------------------------------------------------


@dataclass
class ProviderSet:
    """The provider clients one matching run may use, by name."""

    clients: dict[str, ProviderClient] = field(default_factory=dict)
    cover_client: httpx.Client | None = None

    def get(self, name: str) -> Any:
        return self.clients.get(name)

    def close(self) -> None:
        for client in self.clients.values():
            client.close()
        if self.cover_client is not None:
            self.cover_client.close()


def build_providers(engine: Engine, kind: str, config: MatchingConfig | None = None, *,
                    transport_factory: Any = None) -> ProviderSet:  # fmt: skip
    """Live clients for a library kind ("comics", "manga", "ebooks"), from
    the instance settings; providers without credentials are skipped.
    ``transport_factory(name, secret_params)`` can supply each client's
    transport (the local evaluation records responses this way)."""
    from app.config import get_settings
    from kodex.matching.providers.books import GoogleBooks, Hardcover, OpenLibrary
    from kodex.matching.providers.comicvine import ComicVine
    from kodex.matching.providers.manga import AniList, MangaDex, MangaUpdates
    from kodex.matching.providers.metron import Metron

    config = config or get_config()
    settings = get_settings()
    client_settings = ClientSettings(
        user_agent=settings.enrichment_user_agent,
        timeout=settings.enrichment_http_timeout_seconds,
        search_ttl=dt.timedelta(days=config.search_ttl_days),
        id_ttl=dt.timedelta(days=config.id_ttl_days),
    )
    factories: dict[str, Any] = {
        "comicvine": lambda: ComicVine(api_key=settings.comicvine_api_key, engine=engine, settings=client_settings),
        "metron": lambda: Metron(username=settings.metron_username, password=settings.metron_password, engine=engine,
                                 settings=client_settings),
        "mangadex": lambda: MangaDex(engine=engine, settings=client_settings),
        "anilist": lambda: AniList(engine=engine, settings=client_settings),
        "mangaupdates": lambda: MangaUpdates(engine=engine, settings=client_settings),
        "open_library": lambda: OpenLibrary(engine=engine, settings=client_settings),
        "google_books": lambda: GoogleBooks(api_key=settings.google_books_api_key, engine=engine, settings=client_settings),
        "hardcover": lambda: Hardcover(token=settings.hardcover_api_token, engine=engine, settings=client_settings),
    }  # fmt: skip
    allowed = {name.strip() for name in settings.matching_providers.split(",") if name.strip()}
    clients: dict[str, ProviderClient] = {}
    for name in config.providers.get(kind, []):
        if allowed and name not in allowed:
            continue
        try:
            client = factories[name]()
        except NotConfigured as exc:
            logger.info("Provider %s skipped: %s", name, exc)
            continue
        if transport_factory is not None:
            client.http._transport = transport_factory(name, client.secret_params)
        clients[name] = client
    # Cover addresses come from the providers' data: never to this machine or its network.
    cover_client = outbound.client(
        timeout=20, headers={"User-Agent": settings.enrichment_user_agent}, follow_redirects=True
    )
    return ProviderSet(clients=clients, cover_client=cover_client)


# --- Evidence ------------------------------------------------------------------


@dataclass
class SeriesContext:
    series: Series
    library: Library
    kind: str
    books: list[Book]
    evidence: Evidence
    refs: list[ExternalRef]
    root: Path


# Editions whose name is part of the collected run's title at the providers
# ("Lantern Keep Compendium"); TPB, HC and the like are not, and "Absolute" is
# also the start of real series names.
_NAMED_EDITIONS = {"Compendium": "Compendium", "Omnibus": "Omnibus", "Deluxe": "Deluxe Edition",
                   "Library": "Library Edition"}  # fmt: skip


def _edition_title(parsed: dict[str, Any]) -> str | None:
    edition = _NAMED_EDITIONS.get(parsed.get("edition") or "")
    series = parsed.get("series")
    return f"{series} {edition}" if edition and series else None


def _collected_title(parsed: dict[str, Any]) -> str | None:
    """A collected volume's own title is part of its run's name at the
    providers: ``Harbour Watch v00 - Stormfront!`` is "Harbour Watch: Stormfront!"."""
    if parsed.get("format") != "collected" or not parsed.get("title") or not parsed.get("series"):
        return None
    return f"{parsed['series']}: {parsed['title']}"


def _most_common(values: list[Any]) -> Any:
    values = [v for v in values if v not in (None, "")]
    return Counter(values).most_common(1)[0][0] if values else None


def library_kind(library: Library) -> str:
    return _KIND_BY_LIBRARY.get(library.library_type.value, "comics")


def gather(db: Session, series: Series, *, libraries_root: Path) -> SeriesContext:
    library = db.get(Library, series.library_id)
    assert library is not None
    root = libraries_root / library.path
    books = list(
        db.scalars(select(Book).where(Book.series_id == series.id, Book.missing_since.is_(None)).order_by(Book.number))
    )
    kind = "manga" if series.format_family == "manga" else library_kind(library)

    titles: list[str] = []
    years: list[int] = []
    publishers: list[str] = []
    numbers: list[str] = []
    volumes: list[str] = []
    languages: list[str] = []
    pages: dict[str, int] = {}
    start_years: list[int] = []
    refs: list[ExternalRef] = []
    any_numbered = False
    for book in books:
        raw = (book.book_metadata.raw if book.book_metadata else None) or {}
        comicinfo = raw.get("comicinfo") or {}
        metron_series = (raw.get("metroninfo") or {}).get("series") or {}
        parsed = book.parsed or {}
        numbered = bool(parsed.get("issue") or parsed.get("volume") or parsed.get("chapter"))
        any_numbered = any_numbered or numbered
        # Only what the files say counts as evidence: values an earlier
        # automatic match wrote (v1 enrichment) would just repeat its
        # mistakes. Hand-set metadata is kept.
        trusted = book.book_metadata is not None and book.book_metadata.source != MetadataSource.ENRICHED
        for title in (
            comicinfo.get("series"),
            metron_series.get("name"),
            comicinfo.get("localized_series"),
            _edition_title(parsed),
            _collected_title(parsed),
            parsed.get("series"),
        ):
            if title:
                titles.append(str(title))
        year = (
            comicinfo.get("year")
            or parsed.get("year")
            or (book.book_metadata.published_year if trusted and book.book_metadata else None)
        )
        if isinstance(year, int):
            years.append(year)
        # Explicit start years: ComicInfo Volume (as a year), MetronInfo,
        # or "(YYYY)" before an issue number. The year of a file without
        # any number is its publication year (a TPB, a one-shot).
        volume = str(comicinfo.get("volume") or "")
        if volume.isdigit() and int(volume) >= 1900:
            start_years.append(int(volume))
        if metron_series.get("start_year"):
            start_years.append(int(metron_series["start_year"]))
        if parsed.get("series_year") and numbered:
            start_years.append(int(parsed["series_year"]))
        publisher = comicinfo.get("publisher") or (
            book.book_metadata.publisher if trusted and book.book_metadata else None
        )
        if publisher:
            publishers.append(str(publisher))
        if language := comicinfo.get("language") or parsed.get("language"):
            languages.append(str(language).lower())
        if kind == "manga":
            label = book.chapter_number
            if not label and book.volume_number:
                volumes.append(book.volume_number)
        elif series.format_family == "collected":
            # TPB volumes against the collected line's list; Marvel's "v00"
            # marks a collection outside any numbering, not a volume 0.
            label = book.volume_number if book.volume_number not in ("0", "00") else None
        else:
            label = book.number_label if book.format in ("issue", "one_shot") else None
        if label:
            numbers.append(label)
            if book.page_count and series.format_family != "collected":
                pages[label] = book.page_count
        refs += identify(Path(book.file_path), root, raw)

    folder = parse_folder(series.path) if series.path else None
    if folder is not None and folder.series_year and any_numbered:
        start_years.append(folder.series_year)  # a Mylar-style "Series (Year)" folder of issues
    folder_title = folder.series if folder else ""
    # Titles from the files first; the series' own name (which v1 could
    # have taken from a wrong match) and the folder last.
    clean_title = parse_folder(series.title).series or series.title
    ordered = [*[t for t, _ in Counter(titles).most_common()], folder_title, clean_title]
    unique_titles: list[str] = []
    for title in ordered:
        if title and norm(title) not in {norm(t) for t in unique_titles}:
            unique_titles.append(title)
    explicit = _most_common(start_years)
    evidence = Evidence(
        kind="manga" if kind == "manga" else "comic" if kind == "comics" else "book",
        titles=unique_titles,
        start_year=explicit or (series.start_year if series.match_status == "manual" else None),
        years=sorted(set(years)),
        publisher=_most_common(publishers),
        numbers=sorted(set(numbers), key=lambda n: (len(n), n)),
        volumes=sorted(set(volumes), key=lambda n: (len(n), n)),
        language=_most_common(languages),
        format_family=series.format_family,
        page_counts=pages,
        book_count=len(books),
    )
    return SeriesContext(
        series=series, library=library, kind=kind, books=books, evidence=evidence, refs=refs, root=root
    )


# --- Candidates ------------------------------------------------------------------


@dataclass
class Outcome:
    decision: Decision
    review: MatchReview | None
    applied: bool
    via: str  # "id" | "search" | "skipped"


class Searcher:
    """Candidate search and decisions from evidence alone, without the
    database: id resolution, provider search with the title prefilter,
    issue lists for the best candidates, scoring. The evaluation uses it
    directly; :class:`Matcher` adds the database around it."""

    def __init__(self, providers: ProviderSet, *, config: MatchingConfig | None = None) -> None:
        self.providers = providers
        self.config = config or get_config()
        self.issue_cache: dict[tuple[str, str], list[IssueRef]] = {}

    # The providers to search, in priority order, for a library kind.
    def _order(self, kind: str) -> list[str]:
        return [name for name in self.config.providers.get(kind, []) if self.providers.get(name) is not None]

    def decide(self, evidence: Evidence, kind: str, *, refs: list[ExternalRef] | None = None, book_count: int = 1,
               negative: set[tuple[str, str]] | None = None, positive: set[tuple[str, str]] | None = None) -> Decision:  # fmt: skip
        """The decision for evidence, as match_series makes it but without
        covers, the review queue or applying anything."""
        by_id = self._resolve_ids(evidence, refs or [], book_count)
        if by_id is not None:
            return Decision("auto", by_id, [by_id], None, f"identified by {by_id.details.get('identified_by')}")
        return decide(evidence, self._candidates(evidence, kind, negative or set(), positive or set()), self.config)

    # 2. Id resolution
    def _resolve_ids(self, evidence: Evidence, refs: list[ExternalRef], book_count: int) -> ScoredCandidate | None:
        counts = Counter((ref.provider, ref.kind, ref.id) for ref in refs)
        books = max(book_count, 1)
        cv = self.providers.get("comicvine")
        metron = self.providers.get("metron")
        run: RunCandidate | None = None
        source = ""
        try:
            series_ids = [
                (p, i, n) for (p, k, i), n in counts.items() if k == "series" and p in ("comicvine", "metron")
            ]
            issue_ids = [(p, i) for (p, k, i), _ in counts.items() if k == "issue" and p in ("comicvine", "metron")]
            if series_ids:
                provider, run_id, count = max(series_ids, key=lambda item: item[2])
                if count >= 0.8 * books or len(series_ids) == 1:
                    if provider == "comicvine" and cv is not None:
                        run, source = cv.get_run(run_id), "comicvine series id"
                    elif provider == "metron" and metron is not None:
                        run, source = metron.get_run(run_id), "metron series id"
            if run is None and issue_ids:
                run_ids: Counter[tuple[str, str]] = Counter()
                for provider, issue_id in issue_ids[:5]:
                    if provider == "comicvine" and cv is not None:
                        run_ids[("comicvine", cv.get_issue(issue_id).run_id)] += 1
                    elif provider == "metron" and metron is not None:
                        run_ids[("metron", metron.get_issue(issue_id).run_id)] += 1
                if run_ids:
                    (provider, run_id), count = run_ids.most_common(1)[0]
                    if count == sum(run_ids.values()):  # every looked-up issue agrees
                        run = cv.get_run(run_id) if provider == "comicvine" else metron.get_run(run_id)
                        source = f"{provider} issue ids"
        except (NotFound, ProviderError) as exc:
            logger.info("Id resolution failed for %s: %s", evidence.titles[:1], exc)
            return None
        if run is None:
            return None
        candidate = score_candidate(evidence, run, self.config, issues=self._issues(run))
        candidate.details["identified_by"] = source
        candidate.positive = sorted({*candidate.positive, "id"})
        return candidate

    # 3–4. Aliases and search
    def _candidates(self, evidence: Evidence, kind: str, negative: set[tuple[str, str]],
                    positive: set[tuple[str, str]]) -> list[ScoredCandidate]:  # fmt: skip
        runs: dict[tuple[str, str], RunCandidate] = {}
        alias_keys = set(positive)
        for provider, run_id in positive:
            client = self.providers.get(provider)
            if client is not None:
                try:
                    runs[(provider, run_id)] = client.get_run(run_id)
                except (NotFound, ProviderError) as exc:
                    logger.info("Alias %s:%s unavailable: %s", provider, run_id, exc)
        for provider in self._order(kind):
            client = self.providers.get(provider)
            for query in evidence.titles[:2]:
                try:
                    found = client.search_runs(query)
                except RateLimited:
                    raise
                except ProviderError as exc:
                    logger.warning("%s search for %r failed: %s", provider, query, exc)
                    continue
                for run in found:
                    runs.setdefault((run.provider, run.id), run)
        # Cheap local prefilter before anything costs more calls.
        kept = [
            run for key, run in runs.items()
            if key not in negative and (key in alias_keys or title_score(evidence.titles, [run.name, *run.aliases])[0] >= self.config.prefilter_ratio_min)
        ]  # fmt: skip
        preliminary = sorted(
            (score_candidate(evidence, run, self.config, alias=(run.provider, run.id) in alias_keys) for run in kept),
            key=lambda c: c.score,
            reverse=True,
        )[: self.config.max_candidates]
        scored = []
        for index, candidate in enumerate(preliminary):
            wanted = evidence.numbers or evidence.volumes
            issues = self._issues(candidate.run) if index < self.config.issue_lists and wanted else None
            scored.append(
                score_candidate(
                    evidence,
                    candidate.run,
                    self.config,
                    issues=issues,
                    alias=(candidate.run.provider, candidate.run.id) in alias_keys,
                )
            )
        return merge_linked(scored, self._order(kind))

    def _issues(self, run: RunCandidate) -> list[IssueRef] | None:
        key = (run.provider, run.id)
        if key in self.issue_cache:
            return self.issue_cache[key]
        client = self.providers.get(run.provider)
        if client is None or not hasattr(client, "list_issues"):
            return None
        try:
            issues: list[IssueRef] = client.list_issues(run.id)
        except RateLimited:
            raise
        except ProviderError as exc:
            logger.info("No issue list for %s:%s: %s", run.provider, run.id, exc)
            return None
        self.issue_cache[key] = issues
        return issues


class Matcher(Searcher):
    """Matches series of one library with the given providers."""

    def __init__(self, db: Session, providers: ProviderSet, *, config: MatchingConfig | None = None,
                 libraries_root: Path | None = None) -> None:  # fmt: skip
        from app.config import get_settings

        super().__init__(providers, config=config)
        self.db = db
        self.libraries_root = libraries_root or get_settings().libraries_root

    def match_series(self, series: Series, *, force: bool = False) -> Outcome:
        if series.match_status in ("manual", "none") and not force:
            return Outcome(Decision("none", None, [], None, f"series is {series.match_status}"), None, False, "skipped")
        context = gather(self.db, series, libraries_root=self.libraries_root)
        if not context.books:
            return Outcome(Decision("none", None, [], None, "no books"), None, False, "skipped")
        if not self._order(context.kind):
            # Nothing to ask (no keys configured): not a "no match".
            return Outcome(Decision("none", None, [], None, "no provider configured"), None, False, "skipped")
        if context.kind == "ebooks":
            return self._match_books(context)

        by_id = self._resolve_ids(context.evidence, context.refs, len(context.books))
        if by_id is not None:
            decision = Decision("auto", by_id, [by_id], None, f"identified by {by_id.details.get('identified_by')}")
            review = self._record(context, decision)
            self._apply(context, by_id, decided_by="auto", review=review)
            return Outcome(decision, review, True, "id")

        negative, positive = self._aliases(series)
        candidates = self._candidates(context.evidence, context.kind, negative, positive)
        decision = decide(context.evidence, candidates, self.config)
        # A winner of the wrong format or language only stands for want of a
        # plausible alternative, which the cover (and a subtitle it
        # confirms) may yet supply.
        flawed = decision.best is not None and any(
            k in decision.best.details for k in ("format_mismatch", "language_mismatch")
        )
        if decision.ranked and (decision.outcome != "auto" or flawed):
            decision = self._with_covers(context, decision)
        review = self._record(context, decision)
        if decision.outcome == "auto" and decision.best is not None:
            self._apply(context, decision.best, decided_by="auto", review=review)
            return Outcome(decision, review, True, "search")
        series.match_status = "review" if decision.outcome == "review" else series.match_status
        self.db.flush()
        return Outcome(decision, review, False, "search")

    def _aliases(self, series: Series) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
        if not series.norm_title:
            return set(), set()
        rows = self.db.scalars(
            select(SeriesAlias).where(
                SeriesAlias.norm_title == series.norm_title,
                (SeriesAlias.library_id == series.library_id) | SeriesAlias.library_id.is_(None),
            )
        )
        negative: set[tuple[str, str]] = set()
        positive: set[tuple[str, str]] = set()
        for alias in rows:
            if alias.year is not None and series.start_year is not None and alias.year != series.start_year:
                continue  # an alias for another run with the same title
            (positive if alias.polarity == "positive" else negative).add((alias.provider, alias.external_id))
        return negative, positive

    # E-books: one decision per book.
    def _match_books(self, context: SeriesContext) -> Outcome:
        from kodex.matching.books_match import match_book

        clients = [self.providers.get(name) for name in self._order("ebooks")]
        outcomes = []
        last: Decision | None = None
        for book in context.books:
            evidence = book_evidence(book)
            if not evidence.title:
                continue
            decision = match_book(evidence, clients, self.config)
            last = decision
            record_book_review(self.db, context.series, book, decision)
            if decision.outcome == "auto" and decision.best is not None:
                apply_book_match(book, decision.best.as_dict())
            outcomes.append(decision.outcome)
        series = context.series
        if outcomes:
            series.match_status = "auto" if all(o == "auto" for o in outcomes) else "review"
            series.matched_at = dt.datetime.now(dt.UTC)
        self.db.flush()
        summary = last or Decision("none", None, [], None, "no books with a title")
        return Outcome(summary, None, all(o == "auto" for o in outcomes) and bool(outcomes), "books")

    # Covers, only while the decision is still open.
    def _with_covers(self, context: SeriesContext, decision: Decision) -> Decision:
        book = _cover_book(context.books)
        if book is None:
            return decision
        page = book_cover_page(context.root / book.file_path, book.file_format,
                               (book.book_metadata.raw if book.book_metadata else None) or {})  # fmt: skip
        if page is None:
            return decision
        try:
            ours = hashes_from_bytes(page)
        except Exception as exc:  # noqa: BLE001 - an unreadable cover is no signal
            logger.info("Unreadable cover in %s: %s", book.file_path, exc)
            return decision
        number = book.number_label if book.format in ("issue", "one_shot") else book.volume_number
        rescored = []
        for index, candidate in enumerate(decision.ranked):
            found: tuple[int | None, bool] = (None, False)
            if index < self.config.cover_top_n and candidate.signals.get("title", 0) >= self.config.cover_min_title:
                found = self._compare_cover(candidate, number, ours, page)
            distance, artwork = found
            if distance is None and not artwork:
                rescored.append(candidate)
                continue
            new = score_candidate(context.evidence, candidate.run, self.config, issues=self.issue_cache.get((candidate.run.provider, candidate.run.id)),
                                  cover_distance=distance, cover_artwork=artwork, alias="alias" in candidate.positive)  # fmt: skip
            new.positive = sorted({*new.positive, *candidate.positive})
            new.members = candidate.members
            for key in ("format_mismatch", "language_mismatch"):
                if key in candidate.details:
                    new.details[key] = candidate.details[key]
                else:
                    new.details.pop(key, None)
            rescored.append(new)
        self._mark_other_covers(rescored)
        return decide(context.evidence, rescored, self.config)

    def _compare_cover(self, candidate: ScoredCandidate, number: str | None, ours: list[str],
                       page: bytes) -> tuple[int | None, bool]:  # fmt: skip
        """(hash distance, same artwork) of our cover against the run's issue
        of the same number, or, for a book without one (a collected edition
        named only by its title), against the run's own cover and its first
        issue's. The artwork is compared only when the hashes don't match."""
        theirs: list[str] = []
        urls: list[str] = []
        for run in candidate.members or [candidate.run]:
            issues = self.issue_cache.get((run.provider, run.id))
            if issues is None:
                issues = self._issues(run) or []
            issue = next((i for i in issues if number and i.number and _same_number(i.number, number)), None)
            if issue is None and (not number or len(issues) <= 1):
                # No number to go by, or a one-volume run that numbers it
                # differently (Marvel's "v00" against Comic Vine's #1).
                first = next((i for i in issues if i.number and _same_number(i.number, "1")), None)
                issue = first or (issues[0] if issues else None)
                if run.cover_url:
                    urls.append(run.cover_url)
            if issue is not None and issue.cover_hash:
                theirs.append(issue.cover_hash)
            elif issue is not None and issue.cover_url:
                urls.append(issue.cover_url)
        images: list[bytes] = []
        if self.providers.cover_client is not None:
            for url in dict.fromkeys(urls):
                try:
                    response = self.providers.cover_client.get(url)
                    response.raise_for_status()
                    theirs += hashes_from_bytes(response.content)
                    images.append(response.content)
                except Exception as exc:  # noqa: BLE001 - a cover we can't fetch is no signal
                    logger.info("Cover %s unavailable: %s", url, exc)
        distance = best_distance(ours, theirs) if theirs else None
        if distance is not None and distance <= self.config.cover_strong:
            return distance, False
        return distance, any(same_artwork(page, image) for image in images)

    @staticmethod
    def _mark_other_covers(rescored: list[ScoredCandidate]) -> None:
        """When one run has our very cover, a run whose cover was compared
        and is only the same artwork, or another picture, is another
        edition: it gives way to the exact one (see score.decide)."""
        if not any(c.details.get("cover_exact") for c in rescored):
            return
        for candidate in rescored:
            checked = "cover_distance" in candidate.details or candidate.details.get("cover_artwork")
            if checked and not candidate.details.get("cover_exact"):
                candidate.details["cover_differs"] = candidate.details.get("cover_distance")

    # 5. Review queue and applying
    def _record(self, context: SeriesContext, decision: Decision) -> MatchReview:
        series = context.series
        review = self.db.scalars(
            select(MatchReview).where(
                MatchReview.kind == "series_match", MatchReview.series_id == series.id, MatchReview.status == "open"
            )
        ).first()
        if review is None:
            review = MatchReview(
                kind="series_match", library_id=series.library_id, series_id=series.id, title=series.title
            )
            self.db.add(review)
        evidence = context.evidence
        review.title = series.title
        review.book_count = evidence.book_count
        review.parsed = {
            "titles": evidence.titles, "start_year": evidence.start_year, "years": evidence.years,
            "publisher": evidence.publisher, "numbers": evidence.numbers[:50], "volumes": evidence.volumes[:50], "format_family": evidence.format_family,
            "kind": evidence.kind, "reason": decision.reason, "ids": [ref.__dict__ for ref in context.refs[:10]],
            "parsed_names": [{"name": Path(b.file_path).name, "parsed": b.parsed} for b in context.books[:5] if b.parsed],
        }  # fmt: skip
        review.candidates = [c.as_dict() for c in decision.ranked[:5]]
        review.best_score = decision.best.score if decision.best else None
        review.status = "auto" if decision.outcome == "auto" else "open"
        review.suggestion = {"outcome": decision.outcome, "margin": decision.margin}
        if review.status == "auto":
            review.decided_at = dt.datetime.now(dt.UTC)
            review.decision = (
                {"action": "auto", "provider": decision.best.run.provider, "id": decision.best.run.id}
                if decision.best
                else None
            )
        self.db.flush()
        return review

    def _apply(self, context: SeriesContext, candidate: ScoredCandidate, *, decided_by: str, review: MatchReview,
               user_id: int | None = None) -> None:  # fmt: skip
        apply_match(self.db, context, candidate, decided_by=decided_by, review=review, user_id=user_id,
                    issues=self._issues(candidate.run))  # fmt: skip


def book_evidence(book: Book) -> Any:
    """What the e-book says about itself comes first: its OPF or PDF
    properties. Then what a person set (in v1 an enrichment picked by hand,
    which can be wrong), then what was read at scan time. What an earlier
    automatic enrichment wrote is used only as far as the file name spells
    its title, since it may be the very match being checked."""
    from kodex.formats.opf import isbn13
    from kodex.formats.pdf import split_authors, usable_title
    from kodex.matching.books_match import BookEvidence, spelled_title

    meta = book.book_metadata
    raw = (meta.raw if meta else None) or {}
    opf, pdf = raw.get("opf") or {}, raw.get("pdf") or {}
    manual = meta if meta is not None and meta.source == MetadataSource.MANUAL else None
    scanned = meta if meta is not None and meta.source == MetadataSource.EMBEDDED else None
    isbns = []
    for value in ((opf.get("identifiers") or {}).get("isbn"), *(pdf.get("isbn") or []), manual.isbn if manual else None,
                  scanned.isbn if scanned else None):  # fmt: skip
        if value and (normalised := isbn13(str(value))) and normalised not in isbns:
            isbns.append(normalised)
    year = None
    for value in (opf.get("date"), manual.published_year if manual else None,
                  scanned.published_year if scanned else None):  # fmt: skip
        text = str(value or "")
        if text[:4].isdigit():
            year = int(text[:4])
            break
    stem = Path(book.file_path).stem
    file_names = list(dict.fromkeys(n for n in (stem, stem.split("_")[0], (book.parsed or {}).get("title")) if n))
    titles = [
        t
        for t in (
            opf.get("title"),
            usable_title(pdf.get("title")),
            manual.title if manual else None,
            usable_title(scanned.title) if scanned else None,
            spelled_title(meta.title, file_names) if meta is not None else None,
        )
        if t
    ]
    titles = list(dict.fromkeys([*titles, *file_names]))
    authors = (
        opf.get("authors")
        or pdf.get("authors")
        or (manual.authors if manual else None)
        or (split_authors("; ".join(scanned.authors)) if scanned and scanned.authors else None)
        or []
    )
    return BookEvidence(
        title=str(titles[0]),
        authors=list(authors),
        year=year,
        isbn=isbns,
        language=opf.get("language") or (meta.language if meta else None),
        names=titles[1:],
    )


def record_book_review(db: Session, series: Series, book: Book, decision: Decision) -> MatchReview:
    review = db.scalars(
        select(MatchReview).where(
            MatchReview.kind == "book_match", MatchReview.book_id == book.id, MatchReview.status == "open"
        )
    ).first()
    if review is None:
        review = MatchReview(kind="book_match", library_id=series.library_id, series_id=series.id, book_id=book.id,
                             title=book.book_metadata.title if book.book_metadata else Path(book.file_path).stem)  # fmt: skip
        db.add(review)
    review.book_count = 1
    review.candidates = [c.as_dict() for c in decision.ranked[:5]]
    review.best_score = decision.best.score if decision.best else None
    review.parsed = {"kind": "book", "reason": decision.reason, "titles": [review.title],
                     "parsed_names": [{"name": Path(book.file_path).name, "parsed": book.parsed}] if book.parsed else []}  # fmt: skip
    review.suggestion = {"outcome": decision.outcome, "margin": decision.margin}
    review.status = "auto" if decision.outcome == "auto" else "open"
    if review.status == "auto" and decision.best is not None:
        review.previous = {"book_external_ids": book.book_metadata.external_ids if book.book_metadata else None}
        review.decision = {"action": "auto", "provider": decision.best.run.provider, "id": decision.best.run.id}
        review.decided_at = dt.datetime.now(dt.UTC)
    db.flush()
    return review


def apply_book_match(book: Book, candidate: dict[str, Any]) -> None:
    """The candidate's ids go into the book's external ids, and its
    publisher and year fill empty, unlocked fields."""
    meta = book.book_metadata
    if meta is None:
        return
    external = dict(meta.external_ids or {})
    for key, value in (candidate.get("links") or {}).items():
        external[key if key in ("isbn",) or key.endswith("_work") else f"{key}_id"] = value
    meta.external_ids = external
    locked = set(meta.locked_fields or [])
    if candidate.get("publisher") and not meta.publisher and "publisher" not in locked:
        meta.publisher = candidate["publisher"]
    if candidate.get("start_year") and not meta.published_year and "published_year" not in locked:
        meta.published_year = candidate["start_year"]


def _cover_book(books: list[Book]) -> Book | None:
    """The book whose cover stands for the series: a numbered issue, else a
    numbered collected volume, else any book (an annual's cover says least)."""
    return (
        next((b for b in books if b.format in ("issue", "one_shot") and b.number_label), None)
        or next((b for b in books if b.format == "collected" and b.volume_number), None)
        or next((b for b in books if b.format != "annual"), None)
    )


def _same_number(a: str, b: str) -> bool:
    from kodex.matching.parse import normalize_number

    try:
        return normalize_number(a) == normalize_number(b)
    except ValueError:
        return a.strip().lower() == b.strip().lower()


def _snapshot(db: Session, context: SeriesContext) -> dict[str, Any]:
    series = context.series
    externals = [
        {"provider": e.provider, "external_id": e.external_id, "is_primary": e.is_primary, "source": e.source}
        for e in db.scalars(select(SeriesExternalId).where(SeriesExternalId.series_id == series.id))
    ]
    return {
        "series": {
            **{f: getattr(series, f) for f in SERIES_FIELDS},
            "match_status": series.match_status, "match_confidence": series.match_confidence,
            "comicvine_volume_id": series.comicvine_volume_id,
        },
        "external_ids": externals,
        "books": {
            str(b.id): {"issue_unresolved": b.issue_unresolved,
                        "external_ids": (b.book_metadata.external_ids if b.book_metadata else None)}
            for b in context.books
        },
    }  # fmt: skip


def apply_match(db: Session, context: SeriesContext, candidate: ScoredCandidate, *, decided_by: str,
                review: MatchReview, user_id: int | None = None, issues: list[IssueRef] | None = None) -> None:  # fmt: skip
    """Binds the series to ``candidate``: external ids (with every linked
    provider's id), empty unlocked series fields, and each book's issue
    id. The previous state is kept on the review for reverting."""
    series = context.series
    review.previous = _snapshot(db, context)
    run = candidate.run
    known = {
        (e.provider, e.external_id): e
        for e in db.scalars(select(SeriesExternalId).where(SeriesExternalId.series_id == series.id))
    }
    for existing in known.values():
        if existing.provider == run.provider:
            existing.is_primary = False
    ids = {(run.provider, run.id): "auto" if decided_by == "auto" else "manual"}
    for member in candidate.members or [run]:
        ids.setdefault((member.provider, member.id), "bridge")
        for provider, external_id in member.links.items():
            ids.setdefault((provider, external_id), "bridge")
    for (provider, external_id), source in ids.items():
        row = known.get((provider, external_id))
        if row is None:
            row = SeriesExternalId(series_id=series.id, provider=provider, external_id=external_id, source=source)
            db.add(row)
        row.is_primary = (provider, external_id) == (run.provider, run.id) or (
            row.is_primary and provider != run.provider
        )
    locked = set(series.locked_fields or [])
    for field_name, value in (
        ("publisher", run.publisher),
        ("start_year", run.start_year),
        ("summary", run.summary),
        ("status", run.status),
    ):
        if value and field_name not in locked and not getattr(series, field_name):
            setattr(series, field_name, value)
    if run.provider == "comicvine" and run.id.isdigit():
        series.comicvine_volume_id = int(run.id)  # read by v1's release check
    elif "comicvine" in run.links and run.links["comicvine"].isdigit():
        series.comicvine_volume_id = int(run.links["comicvine"])
    series.match_status = decided_by if decided_by in ("auto", "manual") else "auto"
    series.match_confidence = candidate.score
    series.match_reason = {
        "signals": candidate.signals,
        "positive": candidate.positive,
        "provider": run.provider,
        "id": run.id,
    }
    series.matched_at = dt.datetime.now(dt.UTC)
    _resolve_issues(db, context, run, issues)
    db.flush()


def _resolve_issues(db: Session, context: SeriesContext, run: RunCandidate, issues: list[IssueRef] | None) -> None:
    """Each book's issue in the run, by number; numbers the run doesn't
    list are flagged (the series match stays)."""
    by_number: dict[str, IssueRef] = {}
    for issue in issues or []:
        if issue.number:
            try:
                from kodex.matching.parse import normalize_number

                by_number.setdefault(normalize_number(issue.number), issue)
            except ValueError:
                continue
    for book in context.books:
        if book.format not in ("issue", "one_shot", "chapter") or not book.number_label or not issues:
            continue
        found = by_number.get(book.number_label)
        book.issue_unresolved = found is None
        if found is None:
            continue
        issue = found
        if book.book_metadata is None:
            book.book_metadata = BookMetadata(
                book_id=book.id, title=Path(book.file_path).stem, sort_title=Path(book.file_path).stem
            )
        external = dict(book.book_metadata.external_ids or {})
        external[f"{run.provider}_issue_id"] = issue.id
        for provider, linked in issue.links.items():
            external.setdefault(f"{provider}_issue_id", linked)
        if run.provider == "comicvine":
            external["comicvine_volume_id"] = int(run.id) if run.id.isdigit() else run.id
        book.book_metadata.external_ids = external


# --- Review actions -------------------------------------------------------------


def choose_candidate(db: Session, review: MatchReview, matcher: Matcher, provider: str, external_id: str,
                     user_id: int | None = None) -> None:  # fmt: skip
    """A person picked a candidate: apply it, lock the series against
    automation and remember the choice as an alias. For an e-book review
    the stored candidate is applied to the book."""
    if review.kind == "book_match":
        book = db.get(Book, review.book_id) if review.book_id else None
        chosen = next(
            (c for c in review.candidates or [] if c["provider"] == provider and c["id"] == external_id), None
        )
        if book is None or chosen is None:
            raise ValueError("Unknown book or candidate")
        review.previous = {"book_external_ids": book.book_metadata.external_ids if book.book_metadata else None}
        apply_book_match(book, chosen)
        if book.book_metadata is not None:
            book.book_metadata.locked_fields = sorted({*(book.book_metadata.locked_fields or []), "external_ids"})
        _close(
            review, "resolved", {"action": "choose", "provider": provider, "id": external_id, "aliases": []}, user_id
        )
        return
    series = db.get(Series, review.series_id) if review.series_id else None
    if series is None:
        raise ValueError("The review's series no longer exists")
    client = matcher.providers.get(provider)
    if client is None:
        raise ValueError(f"Provider {provider} is not available")
    run = client.get_run(external_id)
    context = gather(db, series, libraries_root=matcher.libraries_root)
    issues = matcher._issues(run)
    candidate = score_candidate(context.evidence, run, matcher.config, issues=issues)
    apply_match(db, context, candidate, decided_by="manual", review=review, user_id=user_id, issues=issues)
    alias = remember_alias(db, series, provider, external_id, positive=True)
    _close(review, "resolved", {"action": "choose", "provider": provider, "id": external_id,
                                "aliases": [alias.id] if alias else []}, user_id)  # fmt: skip


def mark_no_match(db: Session, review: MatchReview, user_id: int | None = None) -> None:
    """There is no match for this series; automation leaves it alone."""
    series = db.get(Series, review.series_id) if review.series_id else None
    aliases: list[int] = []
    if series is not None:
        review.previous = {"series": {"match_status": series.match_status}}
        series.match_status = "none"
        for candidate in review.candidates or []:
            alias = remember_alias(db, series, candidate["provider"], candidate["id"], positive=False)
            if alias is not None:
                aliases.append(alias.id)
    _close(review, "resolved", {"action": "no_match", "aliases": aliases}, user_id)


def _restore(db: Session, series: Series, previous: dict[str, Any], book_id: int | None = None) -> None:
    if "book_external_ids" in previous and book_id is not None:
        book = db.get(Book, book_id)
        if book is not None and book.book_metadata is not None:
            book.book_metadata.external_ids = previous["book_external_ids"]
    if "external_ids" in previous:
        for row in db.scalars(select(SeriesExternalId).where(SeriesExternalId.series_id == series.id)):
            db.delete(row)
        db.flush()
        for row in previous["external_ids"]:
            db.add(SeriesExternalId(series_id=series.id, **row))
    for key, value in previous.get("series", {}).items():
        setattr(series, key, value)
    for book_id, state in previous.get("books", {}).items():
        book = db.get(Book, int(book_id))
        if book is None:
            continue
        book.issue_unresolved = state["issue_unresolved"]
        if book.book_metadata is not None:
            book.book_metadata.external_ids = state["external_ids"]


def revert_auto(db: Session, review: MatchReview, user_id: int | None = None) -> None:
    """Undoes an automatic decision: the previous ids and fields come back,
    and the rejected candidate becomes a negative alias so it isn't picked
    again."""
    if review.status != "auto" or not review.previous:
        raise ValueError("Only automatic decisions can be reverted")
    series = db.get(Series, review.series_id) if review.series_id else None
    if series is not None:
        _restore(db, series, review.previous, review.book_id)
        series.match_status = "review"
        decision = review.decision or {}
        if decision.get("provider") and decision.get("id"):
            remember_alias(db, series, decision["provider"], decision["id"], positive=False)
    _close(review, "reverted", {"action": "revert", "reverted": review.decision}, user_id)
    db.flush()


def reopen(db: Session, review: MatchReview, user_id: int | None = None) -> None:
    """Undoes a person's decision (a choice or "no match", for instance
    right after a bulk action): the previous state comes back, the aliases
    the decision made are removed, and the review is open again. A
    skipped review just opens again."""
    decision = review.decision or {}
    if review.status == "dismissed":
        review.status, review.decision = "open", None
        review.decided_by_user_id, review.decided_at = user_id, None
        db.flush()
        return
    if review.status != "resolved" or decision.get("action") not in ("choose", "no_match"):
        raise ValueError("Only a choice or a no-match decision can be reopened")
    series = db.get(Series, review.series_id) if review.series_id else None
    if series is not None and review.previous:
        _restore(db, series, review.previous, review.book_id)
        if decision["action"] == "choose":
            series.match_status = "review"
    for alias_id in decision.get("aliases", []):
        alias = db.get(SeriesAlias, alias_id)
        if alias is not None:
            db.delete(alias)
    review.status = "open"
    review.decision = None
    review.decided_by_user_id = user_id
    review.decided_at = None
    db.flush()


def _close(review: MatchReview, status: str, decision: dict[str, Any], user_id: int | None) -> None:
    review.status = status
    review.decision = decision
    review.decided_by_user_id = user_id
    review.decided_at = dt.datetime.now(dt.UTC)
