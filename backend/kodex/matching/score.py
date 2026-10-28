"""Series-level scoring: how well a provider run fits a Kodex series, given
evidence gathered from all of the series' books, and the decision that
follows (``auto``, ``review`` or ``none``).

Signals, each 0–1, or None when the evidence or the candidate lacks it:

- **title**: rapidfuzz WRatio against the run's name and every alias,
  minus a penalty for words on only one side ("Batman Beyond" for
  "Batman"; WRatio alone gives 90 to "Lois Lane" against "Adventures of
  Lois Lane and Friends").
- **year**: the series' start year (or its books' years) against the run's
  span: 1.0, 0.7, 0.4 at 0, 1, 2 years off, falling to 0 at 7. A run that
  starts more than a year after a book was published can't hold it, nor
  can one seven or more years off an explicit start year.
- **issue_coverage**: the share of the books' numbers that the run's issue
  list has. Up to six numbers above the last listed one don't count
  against a run that may still be going.
- **publisher**: equal after dropping "Comics", "Inc." and the like.
- **pages**: page counts against the provider's (1.0, 0.7 within 10 %,
  0.3 within 25 %).
- **cover**: perceptual-hash distance of the cover; a strong match
  counts, a miss is neutral.

The weights in matching.toml are renormalised over the signals that are
present, so a missing signal is neutral rather than negative. The title is
also a gate: below ``title_gate`` the score shrinks with the square of the
title's shortfall, so a namesake with the right year and publisher can't
crowd the real run. ``auto``
needs a score of at least ``auto_min``, a margin of ``auto_margin`` to the
runner-up (or a lone candidate scoring ``auto_single``), and at least
``min_positive_signals`` independent positive signals besides the title.
A candidate of the wrong format (a TPB line for single issues), or a
translated or reprint edition (its publisher's language, from
matching.toml, isn't the files'), is disqualified when a plausible
alternative without that flaw exists: (nearly) the same title, scoring
within the margin. The same run found at
two providers (one carrying the other's id) is one candidate, and that
agreement counts as a positive signal when the title matches.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from rapidfuzz import fuzz

from kodex.matching.config import MatchingConfig
from kodex.matching.normalize import norm, normalize_publisher
from kodex.matching.parse import normalize_number
from kodex.matching.providers.base import IssueRef, RunCandidate

Outcome = Literal["auto", "review", "none"]
_POSITIVE = {"year": 0.7, "issue_coverage": 0.8, "publisher": 0.99, "cover": 0.99, "pages": 0.7}
# How many issues a provider's list may lag behind the newest release.
_LIST_LAG = 6


@dataclass
class Evidence:
    """What a series' books say about it."""

    kind: str
    titles: list[str]
    start_year: int | None = None
    years: list[int] = field(default_factory=list)
    publisher: str | None = None
    numbers: list[str] = field(default_factory=list)
    # Manga volumes, for books that are volumes rather than chapters.
    volumes: list[str] = field(default_factory=list)
    format_family: str = "issue"
    page_counts: dict[str, int] = field(default_factory=dict)
    book_count: int = 0
    # The files' language (an ISO 639-1 code), when known or assumed.
    language: str | None = None


@dataclass
class ScoredCandidate:
    run: RunCandidate
    score: float
    signals: dict[str, float]
    details: dict[str, Any]
    positive: list[str]
    disqualified: str | None = None
    members: list[RunCandidate] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.run.provider,
            "id": self.run.id,
            "name": self.run.name,
            "start_year": self.run.start_year,
            "publisher": self.run.publisher,
            "issue_count": self.run.issue_count,
            "cover_url": self.run.cover_url,
            "url": self.run.url,
            "links": self.run.links,
            "score": round(self.score, 4),
            "signals": {k: round(v, 4) for k, v in self.signals.items()},
            "details": self.details,
            "positive": self.positive,
            "disqualified": self.disqualified,
        }


@dataclass
class Decision:
    outcome: Outcome
    best: ScoredCandidate | None
    ranked: list[ScoredCandidate]
    margin: float | None
    reason: str


# --- Signals --------------------------------------------------------------------


def title_score(queries: list[str], names: list[str]) -> tuple[float, str, str]:
    """The best (score, query, name) over every query variant and every
    candidate name or alias."""
    best = (0.0, "", "")
    for query in queries:
        q_norm = norm(query)
        if not q_norm:
            continue
        q_words = set(q_norm.split())
        for name in names:
            n_norm = norm(name)
            if not n_norm:
                continue
            if q_norm == n_norm or q_norm.replace(" ", "") == n_norm.replace(" ", ""):
                return 1.0, query, name  # "Spider-Man" and "Spiderman" alike
            n_words = set(n_norm.split())
            ratio = fuzz.WRatio(q_norm, n_norm) / 100
            extra = sum(1 for w in n_words if not _fuzzy_in(w, q_words))
            missing = sum(1 for w in q_words if not _fuzzy_in(w, n_words))
            score = max(0.0, ratio - 0.08 * extra - 0.10 * missing)
            if score > best[0]:
                best = (score, query, name)
    return best


def _fuzzy_in(word: str, words: set[str]) -> bool:
    """A word counts as shared when it nearly equals one on the other side
    (a typo, "colour"/"color")."""
    if word in words:
        return True
    return len(word) >= 5 and any(len(other) >= 5 and fuzz.ratio(word, other) >= 90 for other in words)


def title_gate(title: float, gate: float) -> float:
    """Multiplier for candidates whose title isn't (nearly) the series'
    own: a run with every other signal right but another name ("Batman
    Beyond" for "Batman") must not end up a close second."""
    if gate <= 0 or title >= gate:
        return 1.0
    return (title / gate) ** 2


def _decay(years_off: float) -> float:
    if years_off <= 0:
        return 1.0
    if years_off <= 1:
        return 0.7
    if years_off <= 2:
        return 0.4
    return max(0.0, 0.4 * (7 - years_off) / 5)


def run_span(run: RunCandidate, issues: list[IssueRef] | None) -> tuple[int | None, int | None]:
    """The years a run covers: from its issues when known, else its start
    and end years (or an estimate from the issue count, monthly)."""
    years = [issue.year for issue in issues or [] if issue.year]
    if years:
        return min(years), max(years)
    start = run.start_year
    if start is None:
        return None, None
    if run.end_year:
        return start, run.end_year
    if run.issue_count:
        return start, start + run.issue_count // 12 + 1
    return start, None


def year_score(evidence: Evidence, run: RunCandidate, issues: list[IssueRef] | None) -> tuple[float | None, bool]:
    """(score, impossible): impossible when the run starts more than a
    year after one of the books was published."""
    if run.start_year is None:
        return None, False
    if evidence.years and run.start_year > min(evidence.years) + 1:
        return 0.0, True
    if evidence.start_year is not None:
        # An explicit start year seven or more years off is another run.
        years_off = abs(run.start_year - evidence.start_year)
        return _decay(years_off), years_off >= 7
    if not evidence.years:
        return None, False
    start, end = run_span(run, issues)
    low, high = min(evidence.years), max(evidence.years)
    off = 0.0
    if start is not None and low < start:
        off = max(off, start - low)
    if end is not None and high > end + 1:
        off = max(off, high - end - 1)
    return _decay(off), False


def _numbers(values: list[str]) -> set[str]:
    out = set()
    for value in values:
        try:
            out.add(normalize_number(value))
        except ValueError:
            out.add(value.strip().lower())
    return out


def coverage_score(evidence: Evidence, issues: list[IssueRef] | None) -> tuple[float | None, dict[str, Any]]:
    if not evidence.numbers and evidence.volumes and issues:
        return _volume_coverage(evidence.volumes, issues)
    if not evidence.numbers or not issues:
        return None, {}
    listed = _numbers([i.number for i in issues if i.number])
    wanted = _numbers(evidence.numbers)
    numeric = [float(n) for n in listed if _is_float(n)]
    last_year = max((i.year for i in issues if i.year), default=None)
    ongoing = last_year is not None and last_year >= dt.date.today().year - 1
    if ongoing and numeric:
        # A few issues newer than the provider lists yet don't count
        # against it; a run listing 3 of 24 numbers is another run.
        newest = max(numeric)
        wanted = {n for n in wanted if not (_is_float(n) and newest < float(n) <= newest + _LIST_LAG)}
    if not wanted:
        return None, {"ignored": "all numbers are newer than the run's list"}
    found = wanted & listed
    return len(found) / len(wanted), {
        "found": len(found),
        "wanted": len(wanted),
        "missing": sorted(wanted - listed)[:10],
    }


def _volume_coverage(volumes: list[str], issues: list[IssueRef]) -> tuple[float | None, dict[str, Any]]:
    """Manga volumes against the volumes a run's chapters are collected
    in. A list without volumes says nothing; the newest volumes may not be
    listed yet."""
    listed = _numbers([i.volume for i in issues if i.volume])
    numeric = [float(n) for n in listed if _is_float(n)]
    if not numeric:
        return None, {}
    newest = max(numeric)
    wanted = {n for n in _numbers(volumes) if not (_is_float(n) and newest < float(n) <= newest + _LIST_LAG)}
    if not wanted:
        return None, {"ignored": "all volumes are newer than the run's list"}
    found = wanted & listed
    return len(found) / len(wanted), {"by": "volume", "found": len(found), "wanted": len(wanted),
                                      "missing": sorted(wanted - listed)[:10]}  # fmt: skip


def _is_float(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def publisher_score(evidence: Evidence, run: RunCandidate) -> float | None:
    if not evidence.publisher or not run.publisher:
        return None
    a, b = normalize_publisher(evidence.publisher), normalize_publisher(run.publisher)
    if not a or not b:
        return None
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.8
    return 0.0


def pages_score(evidence: Evidence, issues: list[IssueRef] | None) -> float | None:
    if not evidence.page_counts or not issues:
        return None
    by_number = {normalize_number(i.number): i.page_count for i in issues if i.number and i.page_count}
    scores = []
    for number, pages in evidence.page_counts.items():
        theirs = by_number.get(normalize_number(number))
        if not theirs or not pages:
            continue
        diff = abs(pages - theirs) / theirs
        scores.append(1.0 if diff == 0 else 0.7 if diff <= 0.10 else 0.3 if diff <= 0.25 else 0.0)
    return sum(scores) / len(scores) if scores else None


def cover_score(distance: int | None, config: MatchingConfig) -> float | None:
    """A strong match is 1.0; anything else (a weak match, a miss, nothing
    to compare) is neutral: a variant or a new trade dress isn't evidence
    against a run."""
    if distance is None or distance > config.cover_strong:
        return None
    return 1.0


# A format word at the end of a run's name ("Harbour Lights TPB") says what
# the format check already knows, and mustn't cost title points.
_FORMAT_SUFFIX = re.compile(r"[\s:,-]+(?:TPB|TP|HC|OHC|GN|OGN|Omnibus|Hardcover|Trade Paperback)\s*$", re.IGNORECASE)


def _with_plain_names(names: list[str]) -> list[str]:
    plain = [_FORMAT_SUFFIX.sub("", n) for n in names]
    return list(dict.fromkeys([*names, *(p for p in plain if p)]))


def _subtitled(titles: list[str], names: list[str]) -> bool:
    """Whether a name is one of our titles followed by a subtitle."""
    for title in titles:
        ours = norm(title)
        for name in names:
            head = re.split(r"\s*(?::|\s[-–—]\s)\s*", name, maxsplit=1)
            if len(head) == 2 and ours and norm(head[0]) == ours:
                return True
    return False


def publisher_language(publisher: str | None, config: MatchingConfig) -> str | None:
    """The language a publisher's editions are in, per matching.toml:
    ``Panini Verlag`` → ``de``; None for publishers it doesn't list."""
    name = normalize_publisher(publisher or "")
    if not name:
        return None
    if name in config.publisher_languages:
        return config.publisher_languages[name]
    for word in name.split():
        if word in config.publisher_language_words:
            return config.publisher_language_words[word]
    for key, language in config.publisher_languages.items():
        if name.startswith(f"{key} "):
            return language
    return None


def _language_mismatch(evidence: Evidence, run: RunCandidate, config: MatchingConfig) -> str | None:
    if evidence.kind != "comic":
        return None  # a manga's provider language is the original's, not the edition's
    ours = evidence.language or config.comics_language
    language = publisher_language(run.publisher, config)
    if not ours or language is None or language.split("-")[0] == ours.split("-")[0].lower():
        return None
    return language


def _format_matches(evidence: Evidence, run: RunCandidate) -> bool | None:
    if run.format is None:
        return None
    family = evidence.format_family
    if family == "collected":
        return run.format == "collected"
    if family == "issue":
        return run.format in ("issue", "annual", "one_shot")
    if family == "manga":
        return run.format in ("manga", "one_shot")
    return None


# --- Candidates and decisions -----------------------------------------------------


def score_candidate(
    evidence: Evidence,
    run: RunCandidate,
    config: MatchingConfig,
    *,
    issues: list[IssueRef] | None = None,
    cover_distance: int | None = None,
    cover_artwork: bool = False,
    alias: bool = False,
) -> ScoredCandidate:
    signals: dict[str, float] = {}
    details: dict[str, Any] = {}
    title, query, name = title_score(evidence.titles, _with_plain_names([run.name, *run.aliases]))
    signals["title"] = title
    details["title"] = {"query": query, "name": name}

    year, impossible = year_score(evidence, run, issues)
    if year is not None:
        signals["year"] = year
    coverage, coverage_details = coverage_score(evidence, issues)
    if coverage is not None:
        signals["issue_coverage"] = coverage
    if coverage_details:
        details["issue_coverage"] = coverage_details
    if (publisher := publisher_score(evidence, run)) is not None:
        signals["publisher"] = publisher
    if (pages := pages_score(evidence, issues)) is not None:
        signals["pages"] = pages
    if cover_distance is not None:
        details["cover_distance"] = cover_distance
    if (cover := 1.0 if cover_artwork else cover_score(cover_distance, config)) is not None:
        signals["cover"] = cover
        if cover_artwork:
            details["cover_artwork"] = True
        else:
            details["cover_exact"] = True
            # Our very cover confirms a run whose name is ours with a
            # subtitle ("Gulls" for "Gulls: Stormfront"), which the title
            # alone can't; the same artwork may be another volume's.
            if title < 1.0 and _subtitled(evidence.titles, [run.name, *run.aliases]):
                signals["title"] = title = 1.0
                details["title"]["subtitle"] = True

    weights = {k: config.weights.get(k, 0.0) for k in signals}
    total = sum(weights.values())
    score = sum(signals[k] * weights[k] for k in signals) / total if total else 0.0
    score *= title_gate(title, config.title_gate)
    positive = [k for k, threshold in _POSITIVE.items() if signals.get(k, -1) >= threshold]
    if alias:
        positive.append("alias")
        details["alias"] = True
    disqualified = None
    if impossible:
        late = evidence.years and run.start_year is not None and run.start_year > min(evidence.years) + 1
        disqualified = "starts after the books were published" if late else "a different start year"
    format_ok = _format_matches(evidence, run)
    if format_ok is False:
        details["format_mismatch"] = run.format
    if language := _language_mismatch(evidence, run, config):
        details["language_mismatch"] = language
    return ScoredCandidate(
        run=run, score=score, signals=signals, details=details, positive=positive, disqualified=disqualified
    )


def _alike(a: RunCandidate, b: RunCandidate) -> bool:
    """The same run at two providers that don't carry each other's id (a
    Metron collected series without its Comic Vine id): same name without
    a format word, start year and publisher, a similar number of issues
    (one list may lag), and no id of one that points elsewhere at the
    other."""
    if a.provider == b.provider or a.start_year is None or a.start_year != b.start_year:
        return False
    if norm(_FORMAT_SUFFIX.sub("", a.name)) != norm(_FORMAT_SUFFIX.sub("", b.name)):
        return False
    publisher = normalize_publisher(a.publisher or "")
    if not publisher or publisher != normalize_publisher(b.publisher or ""):
        return False
    if (
        a.issue_count
        and b.issue_count
        and abs(a.issue_count - b.issue_count) > max(2, max(a.issue_count, b.issue_count) // 4)
    ):
        return False
    return a.links.get(b.provider, b.id) == b.id and b.links.get(a.provider, a.id) == a.id


def _merge_alike(groups: list[list[ScoredCandidate]]) -> list[list[ScoredCandidate]]:
    """Merges two groups whose runs are alike, but only when neither is
    alike any other group: with two candidates to choose from, it's not
    known which one the other provider means."""

    def leads(group: list[ScoredCandidate]) -> list[RunCandidate]:
        return [c.run for c in group]

    def alike(g: list[ScoredCandidate], h: list[ScoredCandidate]) -> bool:
        formats = {run.format for run in [*leads(g), *leads(h)] if run.format}
        return len(formats) <= 1 and any(_alike(a, b) for a in leads(g) for b in leads(h))

    pairs = {(i, j) for i, g in enumerate(groups) for j, h in enumerate(groups) if i < j and alike(g, h)}
    partners: dict[int, list[int]] = {}
    for i, j in pairs:
        partners.setdefault(i, []).append(j)
        partners.setdefault(j, []).append(i)
    absorbed: set[int] = set()
    result = []
    for i, group in enumerate(groups):
        if i in absorbed:
            continue
        mates = partners.get(i, [])
        if len(mates) == 1 and len(partners.get(mates[0], [])) == 1 and mates[0] not in absorbed:
            absorbed.add(mates[0])
            group = [*group, *groups[mates[0]]]
        result.append(group)
    return result


def merge_linked(candidates: list[ScoredCandidate], order: list[str]) -> list[ScoredCandidate]:
    """The same run at two providers (a Metron series carrying its Comic
    Vine id) is one candidate: the best-scoring member stands for the group
    and the members' positive signals are pooled."""
    groups: list[list[ScoredCandidate]] = []
    for candidate in candidates:
        keys = {(p, i) for p, i in candidate.run.links.items()} | {(candidate.run.provider, candidate.run.id)}
        for group in groups:
            group_keys = {
                k for member in group for k in {*member.run.links.items(), (member.run.provider, member.run.id)}
            }
            if keys & group_keys:
                group.append(candidate)
                break
        else:
            groups.append([candidate])
    # Two databases cataloguing the same run (linked ids) under the same
    # title is an independent signal: obscure editions and namesakes rarely
    # are. Runs that are merely alike (below) don't earn it.
    linked = {
        id(member)
        for group in groups
        if len({c.run.provider for c in group}) >= 2 and max(c.signals.get("title", 0) for c in group) >= 0.95
        for member in group
    }
    groups = _merge_alike(groups)
    merged = []
    for group in groups:
        rank = {p: i for i, p in enumerate(order)}
        best = max(group, key=lambda c: (c.score, -rank.get(c.run.provider, 99)))
        lead = min(group, key=lambda c: rank.get(c.run.provider, 99))
        positive = sorted({p for c in group for p in c.positive})
        if any(id(c) in linked for c in group):
            positive = sorted({*positive, "linked"})
        signals = dict(best.signals)
        for member in group:
            for key, value in member.signals.items():
                signals[key] = max(signals.get(key, 0.0), value)
        details = {**lead.details, **best.details}
        details.pop("format_mismatch", None)
        # Only some providers know a run's format (Metron does, Comic Vine
        # doesn't): a mismatch any member knows of holds for the group.
        mismatches = [c.details["format_mismatch"] for c in group if "format_mismatch" in c.details]
        if mismatches:
            details["format_mismatch"] = mismatches[0]
        # A translation is one only if no member is the original.
        details.pop("language_mismatch", None)
        if all("language_mismatch" in c.details for c in group):
            details["language_mismatch"] = group[0].details["language_mismatch"]
        merged.append(
            ScoredCandidate(
                run=lead.run,
                score=best.score,
                signals=signals,
                details=details,
                positive=positive,
                disqualified=best.disqualified if all(c.disqualified for c in group) else None,
                members=[c.run for c in group],
            )
        )
    return merged


def _flaw_label(flaw: str, value: Any) -> str:
    if flaw == "format_mismatch":
        return f"wrong format ({value})"
    if flaw == "cover_differs":
        return "another edition's cover"
    return "a reprint edition" if value == "reprint" else f"another language ({value})"


def _give_way(eligible: list[ScoredCandidate], config: MatchingConfig) -> list[ScoredCandidate]:
    """A translated or reprint edition, a run of the wrong format, or one
    whose cover isn't ours while another's is, gives way to a plausible
    alternative without that flaw: one with (nearly) the same title that
    scores within the margin (for the cover: one with our very cover).
    Unrelated runs of unknown format don't push the right series out."""
    for flaw in ("language_mismatch", "format_mismatch", "cover_differs"):
        clean = [
            c for c in eligible
            if flaw not in c.details and c.signals.get("title", 0) >= config.title_gate
            and (flaw != "cover_differs" or c.details.get("cover_exact"))
        ]  # fmt: skip
        for candidate in eligible:
            if flaw in candidate.details and any(c.score >= candidate.score - config.auto_margin for c in clean):
                candidate.disqualified = _flaw_label(flaw, candidate.details[flaw])
        eligible = [c for c in eligible if not c.disqualified]
    return eligible


def decide(evidence: Evidence, candidates: list[ScoredCandidate], config: MatchingConfig) -> Decision:
    eligible = _give_way([c for c in candidates if not c.disqualified], config)
    ranked = sorted(eligible, key=lambda c: c.score, reverse=True)
    others = sorted((c for c in candidates if c.disqualified), key=lambda c: c.score, reverse=True)
    if not ranked:
        return Decision("none", None, others, None, "no candidates")
    best = ranked[0]
    margin = best.score - ranked[1].score if len(ranked) > 1 else None
    all_ranked = ranked + others
    if best.score < config.review_min:
        return Decision("none", best, all_ranked, margin, f"best score {best.score:.2f} below {config.review_min}")
    clear = (margin is not None and margin >= config.auto_margin) or (
        margin is None and best.score >= config.auto_single
    )
    if best.score >= config.auto_min and clear and len(best.positive) >= config.min_positive_signals:
        return Decision("auto", best, all_ranked, margin, "score, margin and independent signals all clear")
    reasons = []
    if best.score < config.auto_min:
        reasons.append(f"score {best.score:.2f} < {config.auto_min}")
    if not clear:
        reasons.append(
            f"margin {margin:.2f} < {config.auto_margin}"
            if margin is not None
            else "single candidate below auto_single"
        )
    if len(best.positive) < config.min_positive_signals:
        reasons.append(f"{len(best.positive)} independent signals < {config.min_positive_signals}")
    return Decision("review", best, all_ranked, margin, "; ".join(reasons))
