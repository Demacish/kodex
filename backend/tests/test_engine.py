"""kodex.matching.engine end to end on a synthetic Comic Vine world:
scan a small library, match its series, and use the review actions."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.config import Settings
from app.models.book import Book
from app.models.enums import LibraryType
from app.models.library import Library
from app.models.series import Series
from app.scanning import scanner
from kodex.matching.config import load_config
from kodex.matching.engine import Matcher, ProviderSet, choose_candidate, mark_no_match, revert_auto
from kodex.matching.models import MatchReview, SeriesAlias, SeriesExternalId
from kodex.matching.providers.base import ClientSettings, ReplayTransport
from kodex.matching.providers.comicvine import ComicVine
from tests.providers import synthetic as s

# id, name, start year, publisher, numbers, issue year
RUNS = [
    (100, "Batman", 1940, "DC Comics", range(1, 714), 1990),
    (200, "Batman", 2011, "DC Comics", range(0, 53), 2012),
    (300, "Batman", 2016, "DC Comics", range(1, 159), 2017),
    (400, "Batman Beyond", 2016, "DC Comics", range(1, 51), 2017),
]


def _world() -> list[dict]:
    volumes = [s.cv_volume(rid, name, start, pub, len(numbers)) for rid, name, start, pub, numbers, _ in RUNS]
    records = [s.cv_search("Batman", [rid for rid, *_ in RUNS]), s.cv_volumes(volumes)]
    for rid, _name, _start, _pub, numbers, year in RUNS:
        issues = [s.cv_issue(rid * 10_000 + n, rid, str(n), f"{year}-01-01") for n in numbers]
        for offset in range(0, len(issues), 100):
            records.append(s.cv_issues(rid, issues[offset : offset + 100], offset=offset, total=len(issues)))
        records.append(s.record("GET", s.CV + f"volume/4050-{rid}/", {"format": "json", "field_list": s.RUN_FIELDS},
                                response=s.cv_envelope(volumes[[r[0] for r in RUNS].index(rid)])))  # fmt: skip
    records.append(s.record("GET", s.CV + "issue/4000-3000002/", {"format": "json", "field_list": s.ISSUE_FIELDS},
                            response=s.cv_envelope(s.cv_issue(3000002, 300, "2", "2016-08-01"))))  # fmt: skip
    return records


@pytest.fixture
def world(db_session, tmp_path, monkeypatch):
    root = tmp_path / "libraries"
    (root / "serier").mkdir(parents=True)
    monkeypatch.setattr(scanner, "get_settings", lambda: Settings(libraries_root=root))
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS, grouping_strategy="folder")
    db_session.add(library)
    db_session.commit()
    transport = ReplayTransport(_world(), {"api_key"})
    cv = ComicVine(api_key="k", engine=db_session.get_bind(), settings=ClientSettings(user_agent="kodex-tests"),
                   transport=transport, sleep=lambda seconds: None)  # fmt: skip
    matcher = Matcher(db_session, ProviderSet(clients={"comicvine": cv}), config=load_config(), libraries_root=root)
    return library, root / "serier", matcher, transport


def _cbz(path: Path, comicinfo: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("001.png", path.name.encode())
        if comicinfo:
            zf.writestr("ComicInfo.xml", f"<ComicInfo>{comicinfo}</ComicInfo>")


def _series(db, title):
    return db.query(Series).filter(Series.title == title).one()


def test_auto_match_picks_the_right_run_and_resolves_issues(db_session, world):
    library, folder, matcher, _ = world
    for n in (*range(1, 10), 200):
        _cbz(
            folder / "Batman (2016)" / f"Batman {n:03d} (2016).cbz", "<Publisher>DC Comics</Publisher><Year>2017</Year>"
        )
    scanner.scan_library(db_session, library)
    series = _series(db_session, "Batman (2016)")

    outcome = matcher.match_series(series)

    assert outcome.decision.outcome == "auto", outcome.decision.reason
    assert outcome.decision.best.run.id == "300"
    assert series.match_status == "auto" and series.comicvine_volume_id == 300
    externals = {(e.provider, e.external_id, e.is_primary) for e in db_session.query(SeriesExternalId)}
    assert ("comicvine", "300", True) in externals
    books = {b.number_label: b for b in db_session.query(Book)}
    assert books["1"].book_metadata.external_ids["comicvine_issue_id"] == "3000001"
    assert books["200"].issue_unresolved is True  # the run only has 158 issues
    assert books["9"].issue_unresolved is False
    review = outcome.review
    assert review.status == "auto" and review.candidates[0]["id"] == "300"

    revert_auto(db_session, review)
    assert series.match_status == "review" and series.comicvine_volume_id is None
    assert db_session.query(SeriesExternalId).count() == 0
    assert "comicvine_issue_id" not in (books["1"].book_metadata.external_ids or {})
    negative = db_session.query(SeriesAlias).one()
    assert (negative.external_id, negative.polarity) == ("300", "negative")

    again = matcher.match_series(series)
    assert again.decision.best is None or again.decision.best.run.id != "300"


def test_m15_an_embedded_issue_id_identifies_the_run_without_searching(db_session, world):
    library, folder, matcher, transport = world
    web = "<Web>https://comicvine.gamespot.com/batman-2/4000-3000002/</Web>"
    _cbz(folder / "Unsorted" / "whatever.cbz", f"<Number>2</Number>{web}")
    scanner.scan_library(db_session, library)

    outcome = matcher.match_series(_series(db_session, "Unsorted"))

    assert outcome.via == "id" and outcome.decision.best.run.id == "300"
    assert not any("search/" in call for call in transport.calls)


def test_m02_without_a_year_goes_to_review_and_a_choice_becomes_an_alias(db_session, world):
    library, folder, matcher, _ = world
    _cbz(folder / "Batman" / "Batman 001.cbz")
    _cbz(folder / "Batman" / "Batman 002.cbz")
    scanner.scan_library(db_session, library)
    series = _series(db_session, "Batman")

    outcome = matcher.match_series(series)

    assert outcome.decision.outcome == "review"
    review = db_session.query(MatchReview).filter(MatchReview.kind == "series_match").one()
    assert review.status == "open" and len(review.candidates) >= 3
    assert review.parsed["titles"][0] == "Batman"

    choose_candidate(db_session, review, matcher, "comicvine", "200")
    assert series.match_status == "manual" and series.comicvine_volume_id == 200
    assert review.status == "resolved"
    alias = db_session.query(SeriesAlias).one()
    assert (alias.norm_title, alias.external_id, alias.polarity) == ("batman", "200", "positive")
    # A manual match is never redone automatically.
    assert matcher.match_series(series).via == "skipped"


def test_no_match_locks_the_series(db_session, world):
    library, folder, matcher, _ = world
    _cbz(folder / "Batman" / "Batman 001.cbz")
    scanner.scan_library(db_session, library)
    series = _series(db_session, "Batman")
    matcher.match_series(series)
    review = db_session.query(MatchReview).one()

    mark_no_match(db_session, review)

    assert series.match_status == "none"
    assert db_session.query(SeriesAlias).filter(SeriesAlias.polarity == "negative").count() == len(review.candidates)
    assert matcher.match_series(series).via == "skipped"


def test_edition_and_collected_titles_are_searched_too():
    from kodex.matching.engine import _collected_title, _edition_title

    assert _edition_title({"series": "Lantern Keep", "edition": "Compendium"}) == "Lantern Keep Compendium"
    assert _edition_title({"series": "Harbour Lights", "edition": "Absolute"}) is None  # also starts series names
    assert (
        _collected_title({"series": "Harbour Watch", "title": "Stormfront!", "format": "collected"})
        == "Harbour Watch: Stormfront!"
    )
    assert _collected_title({"series": "Harbour Watch", "title": "The Long Night", "format": "issue"}) is None
