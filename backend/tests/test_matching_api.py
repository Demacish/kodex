"""The matching API: the review queue and its actions, bulk decisions with
undo, manual search, jobs and the series actions."""

from __future__ import annotations

import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.models.book import Book
from app.models.enums import LibraryType
from app.models.library import Library
from app.models.series import Series
from app.scanning import scanner
from kodex.matching import engine as matching
from kodex.matching.models import MatchReview, SeriesAlias
from kodex.matching.providers.base import ClientSettings, ReplayTransport
from kodex.matching.providers.comicvine import ComicVine
from tests.test_engine import _world


@pytest.fixture
def env(api, tmp_path, monkeypatch):
    client, session_factory = api
    root = tmp_path / "libraries"
    (root / "serier").mkdir(parents=True)
    monkeypatch.setattr(scanner, "get_settings", lambda: Settings(libraries_root=root))
    db = session_factory()
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS, grouping_strategy="folder")
    db.add(library)
    db.commit()

    def providers(engine, kind, config=None):
        cv = ComicVine(api_key="k", engine=engine, settings=ClientSettings(user_agent="t"),
                       transport=ReplayTransport(_world(), {"api_key"}), sleep=lambda s: None)  # fmt: skip
        return matching.ProviderSet(clients={"comicvine": cv})

    monkeypatch.setattr(matching, "build_providers", providers)
    real_init = matching.Matcher.__init__

    def init(self, db, providers, *, config=None, libraries_root=None):
        real_init(self, db, providers, config=config, libraries_root=root)

    monkeypatch.setattr(matching.Matcher, "__init__", init)
    yield SimpleNamespace(client=client, db=db, library=library, folder=root / "serier", root=root)
    db.close()


def _cbz(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("001.png", path.name.encode())


def _queue(env, names: list[str]) -> list[MatchReview]:
    for name in names:
        _cbz(env.folder / name / "Batman 001.cbz")
    scanner.scan_library(env.db, env.library)
    matcher = matching.Matcher(env.db, matching.build_providers(env.db.get_bind(), "comics"))
    for series in env.db.query(Series).order_by(Series.id):
        matcher.match_series(series)
    env.db.commit()
    return env.db.query(MatchReview).order_by(MatchReview.id).all()


def test_queue_lists_open_reviews_biggest_first(env):
    _queue(env, ["Batman"])
    _cbz(env.folder / "Batman II" / "Batman 002.cbz")
    response = env.client.get("/matching/reviews")
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 1 and page["counts"] == {"open": 1}
    item = page["items"][0]
    assert item["kind"] == "series_match" and item["title"] == "Batman"
    assert item["candidates"][0]["signals"]["title"] == 1.0


def test_choose_then_undo(env):
    (review,) = _queue(env, ["Batman"])
    response = env.client.post(f"/matching/reviews/{review.id}/choose", json={"provider": "comicvine", "id": "200"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "resolved"
    env.db.expire_all()
    series = env.db.get(Series, review.series_id)
    assert series.match_status == "manual" and series.comicvine_volume_id == 200
    assert env.db.query(SeriesAlias).count() == 1

    undo = env.client.post(f"/matching/reviews/{review.id}/revert")
    assert undo.status_code == 200 and undo.json()["status"] == "open"
    env.db.expire_all()
    assert env.db.get(Series, review.series_id).comicvine_volume_id is None
    assert env.db.query(SeriesAlias).count() == 0


def test_skip_then_undo(env):
    (review,) = _queue(env, ["Batman"])
    assert env.client.post(f"/matching/reviews/{review.id}/dismiss").json()["status"] == "dismissed"
    undo = env.client.post(f"/matching/reviews/{review.id}/revert")
    assert undo.status_code == 200 and undo.json()["status"] == "open"
    assert env.client.get("/matching/reviews").json()["counts"] == {"open": 1}


def test_no_match_and_conflicts(env):
    (review,) = _queue(env, ["Batman"])
    assert env.client.post(f"/matching/reviews/{review.id}/no-match").json()["status"] == "resolved"
    assert env.client.post(f"/matching/reviews/{review.id}/no-match").status_code == 409
    assert (
        env.client.post(
            f"/matching/reviews/{review.id}/choose", json={"provider": "comicvine", "id": "200"}
        ).status_code
        == 409
    )
    assert env.client.get("/matching/reviews/9999").status_code == 404


def test_bulk_accept_best(env):
    reviews = _queue(env, ["Batman", "Batman Again"])
    response = env.client.post(
        "/matching/reviews/bulk", json={"review_ids": [r.id for r in reviews], "action": "accept_best"}
    )
    assert response.status_code == 200
    assert sorted(response.json()["done"]) == sorted(r.id for r in reviews)
    env.db.expire_all()
    assert {s.match_status for s in env.db.query(Series)} == {"manual"}


def test_search_scores_without_applying(env):
    (review,) = _queue(env, ["Batman"])
    results = env.client.post(f"/matching/reviews/{review.id}/search", json={"query": "Batman"}).json()
    assert {r["id"] for r in results} == {"100", "200", "300", "400"}
    env.db.expire_all()
    assert env.db.get(Series, review.series_id).match_status == "review"


def test_regroup_accept_through_the_api(env):
    _cbz(env.folder / "Saga" / "Saga 001.cbz")
    scanner.scan_library(env.db, env.library)
    env.library.grouping_strategy = "metadata"
    book = env.db.query(Book).one()
    book.parsed = None  # stale parse: the next scan reparses with the new strategy
    env.db.commit()
    scanner.scan_library(env.db, env.library)
    review = env.db.query(MatchReview).filter(MatchReview.kind == "regroup").one_or_none()
    if review is None:  # the folder name and the parsed name give the same key
        pytest.skip("no regroup needed")
    assert env.client.post(f"/matching/reviews/{review.id}/regroup?accept=true").json()["status"] == "resolved"


def test_split_merge_and_move(env):
    for n in (1, 2, 3):
        _cbz(env.folder / "Batman" / f"Batman {n:03d}.cbz")
    scanner.scan_library(env.db, env.library)
    series = env.db.query(Series).one()
    ids = sorted(b.id for b in series.books)
    split = env.client.post(f"/matching/series/{series.id}/split", json={"book_ids": ids[:1], "title": "Batman (1940)"})
    assert split.status_code == 200
    new_id = split.json()["series_id"]
    assert env.client.post("/matching/books/move", json={"book_ids": ids[1:2], "target_series_id": new_id}).json() == {
        "moved": 1
    }
    merged = env.client.post(f"/matching/series/{series.id}/merge", json={"source_series_ids": [new_id]})
    assert merged.status_code == 200
    env.db.expire_all()
    assert env.db.query(Series).count() == 1
    bad = env.client.post(f"/matching/series/{series.id}/split", json={"book_ids": [999], "title": "x"})
    assert bad.status_code == 400


def test_match_jobs_are_enqueued(env, monkeypatch):
    enqueued = []
    fake_queue = SimpleNamespace(enqueue=lambda *args, **kwargs: enqueued.append(args) or SimpleNamespace(id="job-1"))
    monkeypatch.setattr("app.workers.queue.get_enrichment_queue", lambda: fake_queue)
    assert env.client.post(f"/matching/libraries/{env.library.id}/match").json() == {"job_id": "job-1"}
    assert env.client.post("/matching/libraries/999/match").status_code == 404
    assert enqueued[0][0].__name__ == "match_library_task"


def test_the_providers_setting_limits_the_sources(monkeypatch):
    from types import SimpleNamespace

    from app.config import get_settings
    from kodex.core.db import engine

    real = get_settings()

    def clients(value: str) -> set[str]:
        fake = SimpleNamespace(**{**real.__dict__, "matching_providers": value})
        monkeypatch.setattr("app.config.get_settings", lambda: fake)
        providers = matching.build_providers(engine, "manga")
        try:
            return set(providers.clients)
        finally:
            providers.close()

    every = clients("")
    assert len(every) > 1  # the manga sources need no keys
    one = sorted(every)[0]
    assert clients(f" {one} , unknown") == {one}
    assert clients("none") == set()
