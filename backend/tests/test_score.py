"""kodex.matching.score: signals, renormalised weights and decisions,
including the plan's special cases M-01, M-02, M-03 and M-05."""

from __future__ import annotations

import pytest

from kodex.matching.config import load_config
from kodex.matching.providers.base import IssueRef, RunCandidate
from kodex.matching.score import (
    Evidence,
    coverage_score,
    decide,
    merge_linked,
    publisher_language,
    publisher_score,
    score_candidate,
    title_score,
    year_score,
)

CONFIG = load_config()


def _run(
    rid, name, start, *, publisher="DC Comics", count=None, aliases=(), fmt=None, provider="comicvine", links=None
):
    return RunCandidate(provider=provider, id=str(rid), name=name, start_year=start, publisher=publisher, issue_count=count,
                        aliases=list(aliases), format=fmt, links=links or {provider: str(rid)})  # fmt: skip


def _issues(run_id, numbers, year):
    return [
        IssueRef(provider="comicvine", id=f"{run_id}-{n}", run_id=str(run_id), number=str(n), year=year)
        for n in numbers
    ]


def _batman_runs():
    return [
        (_run(1, "Batman", 1940, count=713), _issues(1, range(1, 714), 1990)),
        (_run(2, "Batman", 2011, count=52), _issues(2, range(0, 53), 2012)),
        (_run(3, "Batman", 2016, count=158), _issues(3, range(1, 159), 2018)),
        (_run(4, "Batman Beyond", 2016, count=50), _issues(4, range(1, 51), 2017)),
    ]


@pytest.mark.parametrize(
    ("query", "name", "low", "high"),
    [
        ("Batman", "Batman", 1.0, 1.0),
        ("The Amazing Spider-Man", "Amazing Spider-Man", 1.0, 1.0),
        ("Batman", "Batman Beyond", 0.75, 0.90),
        ("Spider-Man", "Spiderman", 1.0, 1.0),
        ("Colour of Magic", "Color of Magic", 0.9, 1.0),
        ("Lois Lane", "Adventures of Lois Lane and Friends", 0.0, 0.70),
        ("Saga", "Sagan om ringen", 0.0, 0.6),
        ("Hoshi no Uta", "Hoshi no Uta Anthology", 0.75, 0.9),
    ],
)
def test_title_score_penalises_extra_words(query, name, low, high):
    score, _, _ = title_score([query], [name])
    assert low <= score <= high


def test_title_score_uses_aliases_and_query_variants():
    score, query, name = title_score(["Hoshi no Uta", "Song of the Stars"], ["星の歌", "Song of the Stars"])
    assert (score, query, name) == (1.0, "Song of the Stars", "Song of the Stars")


def test_year_score_decays_and_rules_out_runs_that_start_too_late():
    evidence = Evidence(kind="comic", titles=["Batman"], start_year=2016)
    assert year_score(evidence, _run(1, "Batman", 2016), None) == (1.0, False)
    assert year_score(evidence, _run(1, "Batman", 2017), None)[0] == 0.7
    assert year_score(evidence, _run(1, "Batman", 2011), None) == (pytest.approx(0.16), False)
    assert year_score(evidence, _run(1, "Batman", 1940), None) == (0.0, True)
    late = Evidence(kind="comic", titles=["Batman"], years=[2012])
    assert year_score(late, _run(1, "Batman", 2016), None) == (0.0, True)


def test_coverage_ignores_numbers_newer_than_an_ongoing_runs_list():
    import datetime as dt

    this_year = dt.date.today().year
    issues = _issues(1, range(1, 11), this_year)
    evidence = Evidence(kind="comic", titles=["x"], numbers=["1", "2", "11", "12"])
    score, details = coverage_score(evidence, issues)
    assert score == 1.0 and details["wanted"] == 2
    ended = _issues(1, range(1, 11), 2001)
    assert coverage_score(evidence, ended)[0] == 0.5


def test_manga_volumes_against_the_volumes_a_runs_chapters_are_in():
    chapters = [IssueRef("mangadex", f"c{n}", "m1", str(n), volume=str((n - 1) // 10 + 1)) for n in range(1, 101)]
    evidence = Evidence(kind="manga", titles=["x"], volumes=["1", "2", "9", "10", "11", "12"])
    score, details = coverage_score(evidence, chapters)
    assert score == 1.0 and details == {"by": "volume", "found": 4, "wanted": 4, "missing": []}
    prototype = [IssueRef("mangadex", "c1", "m2", "1", volume="1")]
    # 2 and 3 may just not be listed yet; 8 and 9 are missing.
    assert (
        coverage_score(Evidence(kind="manga", titles=["x"], volumes=["1", "2", "3", "8", "9"]), prototype)[0] == 1 / 3
    )
    untagged = [IssueRef("mangadex", "c1", "m3", "1")]
    assert coverage_score(evidence, untagged) == (None, {})


@pytest.mark.parametrize(
    ("ours", "theirs", "expected"),
    [
        ("DC Comics", "DC", 1.0),
        ("Image Comics, Inc.", "Image", 1.0),
        ("Marvel", "Marvel Worldwide", 0.8),
        ("Image", "Marvel", 0.0),
    ],
)
def test_publisher_score(ours, theirs, expected):
    assert (
        publisher_score(Evidence(kind="comic", titles=[], publisher=ours), _run(1, "x", 2000, publisher=theirs))
        == expected
    )


def _decide(evidence, runs):
    return decide(evidence, [score_candidate(evidence, run, CONFIG, issues=issues) for run, issues in runs], CONFIG)


def test_m01_same_title_several_runs_book_with_year_is_auto():
    evidence = Evidence(kind="comic", titles=["Batman"], start_year=2016, years=[2016, 2017], publisher="DC Comics",
                        numbers=["1", "2", "3", "15"])  # fmt: skip
    decision = _decide(evidence, _batman_runs())
    assert decision.outcome == "auto", decision.reason
    assert decision.best.run.id == "3"
    assert set(decision.best.positive) >= {"year", "issue_coverage", "publisher"}


def test_m02_same_title_book_without_year_goes_to_review():
    evidence = Evidence(kind="comic", titles=["Batman"], numbers=["1", "2"])
    decision = _decide(evidence, _batman_runs())
    assert decision.outcome == "review"
    assert decision.margin is not None and decision.margin < CONFIG.auto_margin


def test_m03_collected_edition_never_matches_an_issue_run():
    evidence = Evidence(
        kind="comic", titles=["Saga"], start_year=2012, years=[2012], format_family="collected", publisher="Image"
    )
    issues_run = _run(10, "Saga", 2012, publisher="Image", count=72, fmt="issue")
    tpb_run = _run(11, "Saga", 2012, publisher="Image", count=12, fmt="collected")
    decision = decide(evidence, [score_candidate(evidence, r, CONFIG) for r in (issues_run, tpb_run)], CONFIG)
    assert decision.best.run.id == "11"
    assert any(c.run.id == "10" and c.disqualified for c in decision.ranked)


def test_m05_renumbering_is_judged_on_the_issue_list_not_the_count():
    evidence = Evidence(
        kind="comic", titles=["Action Comics"], years=[2018], publisher="DC Comics", numbers=["1000", "1001"]
    )
    legacy = _run(20, "Action Comics", 1938, count=900)
    legacy_issues = _issues(20, [*range(1, 905), 1000, 1001], 2018)
    reboot = _run(21, "Action Comics", 2011, count=52)
    reboot_issues = _issues(21, range(0, 53), 2013)
    decision = _decide(evidence, [(legacy, legacy_issues), (reboot, reboot_issues)])
    assert decision.best.run.id == "20"
    assert decision.best.signals["issue_coverage"] == 1.0


def test_missing_signals_are_neutral():
    run = _run(1, "Hoshi no Uta", None, publisher=None)
    candidate = score_candidate(Evidence(kind="manga", titles=["Hoshi no Uta"]), run, CONFIG)
    assert candidate.signals == {"title": 1.0}
    assert candidate.score == 1.0  # renormalised over the one signal present


def test_title_alone_is_never_enough_for_auto():
    evidence = Evidence(kind="manga", titles=["Hoshi no Uta"])
    decision = decide(evidence, [score_candidate(evidence, _run(1, "Hoshi no Uta", None), CONFIG)], CONFIG)
    assert decision.outcome == "review"
    assert "independent signals" in decision.reason


def test_a_strong_cover_match_counts_as_a_signal():
    evidence = Evidence(kind="comic", titles=["Batman"], start_year=2016)
    candidate = score_candidate(evidence, _run(3, "Batman", 2016), CONFIG, cover_distance=4)
    assert "cover" in candidate.positive and candidate.signals["cover"] == 1.0
    miss = score_candidate(evidence, _run(3, "Batman", 2016), CONFIG, cover_distance=30)
    assert "cover" not in miss.signals


def test_low_scores_give_none():
    evidence = Evidence(kind="comic", titles=["Saga"], start_year=2012)
    decision = decide(evidence, [score_candidate(evidence, _run(1, "Batman Beyond", 1999), CONFIG)], CONFIG)
    assert decision.outcome == "none"


def test_linked_candidates_merge_into_one():
    evidence = Evidence(kind="comic", titles=["Batman"], start_year=2016, publisher="DC Comics")
    cv = score_candidate(evidence, _run(3, "Batman", 2016), CONFIG)
    metron = score_candidate(
        evidence, _run(77, "Batman", 2016, provider="metron", links={"metron": "77", "comicvine": "3"}), CONFIG
    )
    other = score_candidate(evidence, _run(2, "Batman", 2011), CONFIG)
    merged = merge_linked([metron, cv, other], ["comicvine", "metron"])
    assert len(merged) == 2
    lead = next(c for c in merged if len(c.members) == 2)
    assert lead.run.provider == "comicvine"


@pytest.mark.parametrize(
    ("publisher", "language"),
    [
        ("Panini Verlag", "de"),
        ("Panini España", "es"),
        ("Panini Comics", "it"),
        ("Urban Comics", "fr"),
        ("Norma Editorial", "es"),
        ("Editorial Televisa", "es"),
        ("Marvel UK/Panini", "reprint"),
        ("DC Comics", None),
        ("Star Comics", None),  # Marvel's 1980s imprint, not Edizioni Star Comics
        (None, None),
    ],
)
def test_publisher_language(publisher, language):
    assert publisher_language(publisher, CONFIG) == language


def _scored(evidence, *runs, **kwargs):
    return [score_candidate(evidence, run, CONFIG, **kwargs) for run in runs]


def test_a_translation_with_the_same_title_and_year_gives_way_to_the_original():
    evidence = Evidence(kind="comic", titles=["Harbour Lights"], start_year=2025, years=[2025])
    original = _run(1, "Harbour Lights", 2025, publisher="DC Comics", count=3)
    french = _run(2, "Harbour Lights", 2025, publisher="Urban Comics", count=3)
    decision = decide(evidence, _scored(evidence, french, original), CONFIG)
    assert decision.best.run.id == "1" and decision.margin is None
    assert next(c for c in decision.ranked if c.run.id == "2").disqualified == "another language (fr)"
    # Files tagged in French want the French edition.
    french_files = Evidence(kind="comic", titles=["Harbour Lights"], start_year=2025, language="fr")
    assert decide(french_files, _scored(french_files, french, original), CONFIG).best.run.id == "2"


def test_a_translation_stays_when_there_is_no_original_to_prefer():
    evidence = Evidence(kind="comic", titles=["Lantern Keep"], years=[2026])
    translation = _run(1, "Lantern Keep", 2020, publisher="Cross Cult", count=4)
    namesake = _run(2, "The Keep", 2023, publisher="Red Kite", count=5)
    decision = decide(evidence, _scored(evidence, translation, namesake), CONFIG)
    assert decision.best.run.id == "1" and not decision.best.disqualified


def test_a_wrong_format_gives_way_only_to_a_plausible_alternative():
    tpb = Evidence(kind="comic", titles=["Driftwood"], years=[2025], format_family="collected")
    issues = _run(1, "Driftwood", 2025, publisher="Northwind Comics", count=4, fmt="issue")
    namesakes = [_run(n, "Driftwood", year, publisher="Atlas Lane", count=4) for n, year in ((2, 2015), (3, 2016))]
    decision = decide(tpb, _scored(tpb, issues, *namesakes), CONFIG)
    assert decision.best.run.id == "1"  # ten-year-old namesakes don't push it out
    collected = _run(4, "Driftwood", 2025, publisher="Northwind Comics", count=1)
    decision = decide(tpb, _scored(tpb, issues, collected, *namesakes), CONFIG)
    assert decision.best.run.id == "4" and next(c for c in decision.ranked if c.run.id == "1").disqualified


def test_the_same_collected_run_at_two_providers_without_ids_is_one_candidate():
    evidence = Evidence(kind="comic", titles=["Quiet Coast"], years=[2025, 2026], numbers=["1", "2"],
                        format_family="collected")  # fmt: skip
    cv = _run(1, "Quiet Coast", 2025, count=2)
    metron = _run(7, "Quiet Coast TPB", 2025, count=1, fmt="collected", provider="metron")
    ongoing = _run(2, "Quiet Coast", 2025, count=20)  # same name and year, but 20 issues
    merged = merge_linked(_scored(evidence, cv, metron, ongoing), ["comicvine", "metron"])
    assert sorted(len(c.members) for c in merged) == [1, 2]
    pair = next(c for c in merged if len(c.members) == 2)
    assert {r.id for r in pair.members} == {"1", "7"} and "linked" not in pair.positive
    # With two Comic Vine runs it could be, Metron's is left alone.
    twin = _run(3, "Quiet Coast", 2025, count=3)
    assert all(len(c.members) == 1 for c in merge_linked(_scored(evidence, cv, metron, twin), ["comicvine", "metron"]))


def test_our_very_cover_confirms_a_subtitle_but_the_artwork_alone_does_not():
    evidence = Evidence(kind="comic", titles=["Gulls"], years=[2016], format_family="collected")
    run = _run(1, "Gulls: Stormfront", 2016, publisher="Northwind Comics", count=1)
    plain = score_candidate(evidence, run, CONFIG)
    exact = score_candidate(evidence, run, CONFIG, cover_distance=0)
    artwork = score_candidate(evidence, run, CONFIG, cover_distance=22, cover_artwork=True)
    assert plain.signals["title"] < CONFIG.title_gate
    assert exact.signals["title"] == 1.0 and exact.details["title"]["subtitle"]
    assert artwork.signals["title"] == plain.signals["title"] and "cover" in artwork.positive


def test_a_weak_cover_match_is_neutral():
    evidence = Evidence(kind="comic", titles=["Batman"], start_year=2016)
    weak = score_candidate(evidence, _run(3, "Batman", 2016), CONFIG, cover_distance=12)
    assert "cover" not in weak.signals and weak.details["cover_distance"] == 12
    assert weak.score == score_candidate(evidence, _run(3, "Batman", 2016), CONFIG).score


def test_another_editions_cover_gives_way_to_ours():
    evidence = Evidence(kind="comic", titles=["Harbour Watch: Red Tide"], years=[2025], format_family="collected")
    mini = score_candidate(evidence, _run(1, "Harbour Watch: Red Tide", 2024, publisher="Northwind Comics", count=5), CONFIG,
                           cover_distance=18, cover_artwork=True)  # fmt: skip
    tpb = score_candidate(evidence, _run(2, "Harbour Watch: Red Tide", 2025, publisher="Northwind Comics", count=1), CONFIG,
                          cover_distance=6)  # fmt: skip
    mini.details["cover_differs"] = 18  # as Matcher._mark_other_covers marks it
    decision = decide(evidence, [mini, tpb], CONFIG)
    assert decision.best.run.id == "2" and decision.outcome == "auto"
    assert next(c for c in decision.ranked if c.run.id == "1").disqualified == "another edition's cover"
