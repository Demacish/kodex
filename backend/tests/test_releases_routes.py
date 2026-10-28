"""API-level tests for B5's release calendar/pull-list:
GET /series/{id}/release-events, GET /releases, POST /releases/{id}/dismiss.
"""

from __future__ import annotations

import datetime as dt

from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.models.metadata import BookMetadata
from app.models.release_event import SeriesReleaseEvent
from app.models.series import Series


def _seed_series(session_factory, *, title: str = "Absolute Corvid", is_following: bool = True) -> int:
    db = session_factory()
    library = Library(name=f"Lib-{title}", path=f"lib-{title}", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    series = Series(library_id=library.id, title=title, sort_title=title, path=title, is_following=is_following)
    db.add(series)
    db.commit()
    series_id = series.id
    db.close()
    return series_id


def _add_event(
    session_factory,
    series_id: int,
    *,
    external_issue_id: str,
    store_date: dt.date | None,
    owned_book_id: int | None = None,
    dismissed: bool = False,
) -> int:
    db = session_factory()
    event = SeriesReleaseEvent(
        series_id=series_id,
        external_issue_id=external_issue_id,
        provider="comicvine",
        issue_number=external_issue_id,
        store_date=store_date,
        owned_book_id=owned_book_id,
        dismissed=dismissed,
    )
    db.add(event)
    db.commit()
    event_id = event.id
    db.close()
    return event_id


PAST = dt.date.today() - dt.timedelta(days=30)
FUTURE = dt.date.today() + dt.timedelta(days=30)


def test_series_release_events_sorted_by_store_date(api):
    client, session_factory = api
    series_id = _seed_series(session_factory)
    _add_event(session_factory, series_id, external_issue_id="2", store_date=FUTURE)
    _add_event(session_factory, series_id, external_issue_id="1", store_date=PAST)
    _add_event(session_factory, series_id, external_issue_id="3", store_date=None)

    response = client.get(f"/series/{series_id}/release-events")
    assert response.status_code == 200
    ids = [e["external_issue_id"] for e in response.json()]
    assert ids == ["1", "2", "3"]  # past first, future second, no-date last


def test_series_release_events_unknown_series_404s(api):
    client, _ = api
    assert client.get("/series/999999/release-events").status_code == 404


def test_release_event_status_unreleased_released_owned(api):
    client, session_factory = api
    series_id = _seed_series(session_factory)

    db = session_factory()
    series = db.get(Series, series_id)
    book = Book(
        library_id=series.library_id,
        series_id=series_id,
        file_path="1.cbz",
        file_format=BookFormat.CBZ,
        file_size=1,
        file_mtime=0.0,
    )
    db.add(book)
    db.flush()
    db.add(BookMetadata(book_id=book.id, title="Owned", sort_title="Owned", external_ids={"comicvine_issue_id": 1}))
    db.commit()
    book_id = book.id
    db.close()

    _add_event(session_factory, series_id, external_issue_id="1", store_date=FUTURE)
    _add_event(session_factory, series_id, external_issue_id="2", store_date=PAST)
    _add_event(session_factory, series_id, external_issue_id="3", store_date=PAST, owned_book_id=book_id)

    events = {e["external_issue_id"]: e for e in client.get(f"/series/{series_id}/release-events").json()}
    assert events["1"]["status"] == "unreleased"
    assert events["2"]["status"] == "released"
    assert events["3"]["status"] == "owned"


def test_releases_pull_list_only_includes_followed_series(api):
    client, session_factory = api
    followed_id = _seed_series(session_factory, title="Followed", is_following=True)
    not_followed_id = _seed_series(session_factory, title="NotFollowed", is_following=False)
    _add_event(session_factory, followed_id, external_issue_id="1", store_date=FUTURE)
    _add_event(session_factory, not_followed_id, external_issue_id="1", store_date=FUTURE)

    response = client.get("/releases")
    assert response.status_code == 200
    series_ids = {e["series_id"] for e in response.json()}
    assert series_ids == {followed_id}


def test_releases_excludes_dismissed_by_default(api):
    client, session_factory = api
    series_id = _seed_series(session_factory)
    _add_event(session_factory, series_id, external_issue_id="1", store_date=FUTURE, dismissed=True)
    _add_event(session_factory, series_id, external_issue_id="2", store_date=FUTURE, dismissed=False)

    default = client.get("/releases").json()
    assert [e["external_issue_id"] for e in default] == ["2"]

    with_dismissed = client.get("/releases", params={"include_dismissed": "true"}).json()
    assert len(with_dismissed) == 2


def test_releases_filters_by_status(api):
    client, session_factory = api
    series_id = _seed_series(session_factory)
    _add_event(session_factory, series_id, external_issue_id="1", store_date=None)  # no date -> "released" (not future)

    all_events = client.get("/releases").json()
    assert len(all_events) == 1

    unreleased = client.get("/releases", params={"status": "unreleased"}).json()
    assert unreleased == []


def test_dismiss_release_event(api):
    client, session_factory = api
    series_id = _seed_series(session_factory)
    event_id = _add_event(session_factory, series_id, external_issue_id="1", store_date=FUTURE)

    response = client.post(f"/releases/{event_id}/dismiss")
    assert response.status_code == 200
    assert response.json()["dismissed"] is True

    assert client.get("/releases").json() == []


def test_dismiss_unknown_release_event_404s(api):
    client, _ = api
    assert client.post("/releases/999999/dismiss").status_code == 404
