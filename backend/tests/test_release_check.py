"""Tests for app/enrichment/release_check.py — the weekly "does this
followed series have a new release?" check (see "Modul: Följda serier" i
arkitekturplanen). check_series_for_new_release() takes its db session as
a plain argument rather than opening its own (unlike the RQ task that
calls it, app.workers.tasks.check_followed_series_task), so it can be
tested directly against an isolated in-memory database without needing to
redirect app.database.SessionLocal (the way the tasks tests do it), since that
gets handled where it can't be avoided.
"""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from app.enrichment.comicvine import IssueRelease
from app.enrichment.release_check import (
    _most_common_external_id,
    _owned_count,
    _sync_release_events,
    check_series_for_new_release,
)
from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.models.metadata import BookMetadata
from app.models.release_event import SeriesReleaseEvent
from app.models.series import Series
from tests.db import fresh_engine


@pytest.fixture
def db():
    engine = fresh_engine()
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()


_book_counter = 0


def _make_book(db, *, series_id: int, library_id: int, number: float, external_ids: dict | None = None) -> Book:
    global _book_counter
    _book_counter += 1
    book = Book(
        library_id=library_id,
        series_id=series_id,
        # Unique regardless of `number` (tests intentionally pass number=None
        # more than once per library to exercise the row-count fallback) —
        # books.(library_id, file_path) is unique, so f"vol-{number}.cbz"
        # alone would collide.
        file_path=f"vol-{number}-{_book_counter}.cbz",
        file_format=BookFormat.CBZ,
        file_size=1,
        file_mtime=0.0,
        number=number,
    )
    db.add(book)
    db.flush()
    if external_ids is not None:
        db.add(
            BookMetadata(
                book_id=book.id, title=f"Volume {number}", sort_title=f"Volume {number}", external_ids=external_ids
            )
        )
    return book


def _make_series(db, *, library_type: LibraryType) -> Series:
    library = Library(name="Test", path="test", library_type=library_type)
    db.add(library)
    db.flush()
    series = Series(library_id=library.id, title="Test Series", sort_title="Test Series", path="Test Series")
    db.add(series)
    db.flush()
    return series


def test_owned_count_prefers_higher_of_max_number_and_row_count(db):
    series = _make_series(db, library_type=LibraryType.COMICS)
    _make_book(db, series_id=series.id, library_id=series.library_id, number=1)
    _make_book(db, series_id=series.id, library_id=series.library_id, number=5)  # missing 2-4
    db.flush()

    # Highest number seen (5) beats the plain row count (2) — a library
    # missing back issues shouldn't look like it only owns 2 issues.
    assert _owned_count(db, series.id) == 5


def test_owned_count_falls_back_to_row_count_when_numbers_missing(db):
    series = _make_series(db, library_type=LibraryType.COMICS)
    _make_book(db, series_id=series.id, library_id=series.library_id, number=None)
    _make_book(db, series_id=series.id, library_id=series.library_id, number=None)
    db.flush()

    assert _owned_count(db, series.id) == 2


def test_most_common_external_id_majority_vote(db):
    series = _make_series(db, library_type=LibraryType.COMICS)
    _make_book(
        db, series_id=series.id, library_id=series.library_id, number=1, external_ids={"comicvine_volume_id": 42}
    )
    _make_book(
        db, series_id=series.id, library_id=series.library_id, number=2, external_ids={"comicvine_volume_id": 42}
    )
    _make_book(
        db, series_id=series.id, library_id=series.library_id, number=3, external_ids={"comicvine_volume_id": 999}
    )
    db.flush()

    assert _most_common_external_id(db, series.id, "comicvine_volume_id") == "42"


def test_most_common_external_id_none_when_nothing_enriched_yet(db):
    series = _make_series(db, library_type=LibraryType.COMICS)
    _make_book(db, series_id=series.id, library_id=series.library_id, number=1)
    db.flush()

    assert _most_common_external_id(db, series.id, "comicvine_volume_id") is None


def test_check_series_comics_detects_new_release(db, monkeypatch):
    series = _make_series(db, library_type=LibraryType.COMICS)
    _make_book(
        db, series_id=series.id, library_id=series.library_id, number=1, external_ids={"comicvine_volume_id": 42}
    )
    _make_book(
        db, series_id=series.id, library_id=series.library_id, number=2, external_ids={"comicvine_volume_id": 42}
    )
    db.flush()

    monkeypatch.setattr("app.enrichment.release_check.comicvine.fetch_issue_count", lambda *a, **kw: 5)
    monkeypatch.setattr("app.enrichment.release_check.comicvine.list_issue_releases", lambda *a, **kw: [])

    result = check_series_for_new_release(db, series, comicvine_api_key="fake-key")

    assert result is True
    assert series.new_release_available is True
    assert series.known_release_count == 5
    assert series.last_release_check_at is not None


def test_check_series_comics_no_new_release_when_counts_match(db, monkeypatch):
    series = _make_series(db, library_type=LibraryType.COMICS)
    _make_book(
        db, series_id=series.id, library_id=series.library_id, number=1, external_ids={"comicvine_volume_id": 42}
    )
    _make_book(
        db, series_id=series.id, library_id=series.library_id, number=2, external_ids={"comicvine_volume_id": 42}
    )
    db.flush()

    monkeypatch.setattr("app.enrichment.release_check.comicvine.fetch_issue_count", lambda *a, **kw: 2)
    monkeypatch.setattr("app.enrichment.release_check.comicvine.list_issue_releases", lambda *a, **kw: [])

    result = check_series_for_new_release(db, series, comicvine_api_key="fake-key")

    assert result is False
    assert series.known_release_count == 2


def test_check_series_manga_uses_anilist(db, monkeypatch):
    series = _make_series(db, library_type=LibraryType.MANGA)
    _make_book(db, series_id=series.id, library_id=series.library_id, number=1, external_ids={"anilist_id": 7})
    db.flush()

    monkeypatch.setattr("app.enrichment.release_check.anilist.fetch_release_count", lambda *a, **kw: 3)

    result = check_series_for_new_release(db, series, comicvine_api_key="")

    assert result is True
    assert series.known_release_count == 3


def test_check_series_without_external_id_leaves_flag_unchanged_but_stamps_check_time(db):
    series = _make_series(db, library_type=LibraryType.COMICS)
    series.new_release_available = True  # a stale flag from some earlier state
    _make_book(db, series_id=series.id, library_id=series.library_id, number=1)  # never enriched
    db.flush()

    result = check_series_for_new_release(db, series, comicvine_api_key="fake-key")

    assert result is True  # unchanged, not reset to False just because we couldn't check
    assert series.known_release_count is None
    assert series.last_release_check_at is not None


def test_check_series_missing_api_key_cant_tell(db, monkeypatch):
    series = _make_series(db, library_type=LibraryType.COMICS)
    _make_book(
        db, series_id=series.id, library_id=series.library_id, number=1, external_ids={"comicvine_volume_id": 42}
    )
    db.flush()

    called = []
    monkeypatch.setattr(
        "app.enrichment.release_check.comicvine.fetch_issue_count", lambda *a, **kw: called.append(1) or 99
    )

    check_series_for_new_release(db, series, comicvine_api_key="")

    # No key configured — never even calls out to Comic Vine, same as the
    # normal enrichment engine's behavior when comicvine_api_key is empty.
    assert called == []
    assert series.known_release_count is None


def test_check_series_ebooks_library_is_a_noop(db):
    series = _make_series(db, library_type=LibraryType.EBOOKS)
    _make_book(
        db,
        series_id=series.id,
        library_id=series.library_id,
        number=1,
        external_ids={"open_library_key": "/works/OL1W"},
    )
    db.flush()

    result = check_series_for_new_release(db, series, comicvine_api_key="fake-key")

    assert result is False
    assert series.known_release_count is None
    assert series.last_release_check_at is not None


# --- B5: release calendar / _sync_release_events ---------------------------


def test_sync_release_events_is_a_noop_when_provider_returns_nothing(db):
    series = _make_series(db, library_type=LibraryType.COMICS)
    db.flush()

    # comicvine.list_issue_releases isn't monkeypatched here on purpose —
    # confirms the "network down -> [] -> no-op" contract documented on
    # list_issue_releases/_sync_release_events: a failed httpx call is
    # caught there and never raises up to here.
    def refuse(request):
        raise httpx.ConnectError("network down", request=request)

    with httpx.Client(transport=httpx.MockTransport(refuse)) as client:
        _sync_release_events(db, series, "42", "fake-key", client=client)

    assert db.query(SeriesReleaseEvent).count() == 0


def test_sync_release_events_creates_and_updates_rows(db, monkeypatch):
    series = _make_series(db, library_type=LibraryType.COMICS)
    db.flush()

    releases = [
        IssueRelease(
            external_id="501",
            issue_number="1",
            title="Issue #1",
            store_date="2026-01-01 00:00:00",
            cover_date="2026-01-01 00:00:00",
        ),
    ]
    monkeypatch.setattr("app.enrichment.release_check.comicvine.list_issue_releases", lambda *a, **kw: releases)

    _sync_release_events(db, series, "42", "fake-key", client=None)
    db.commit()

    assert db.query(SeriesReleaseEvent).count() == 1
    event = db.query(SeriesReleaseEvent).one()
    assert event.external_issue_id == "501"
    assert event.issue_number == "1"
    assert event.store_date == dt.date(2026, 1, 1)

    # Re-sync with an updated store_date for the same issue -> update, not duplicate.
    updated_releases = [
        IssueRelease(
            external_id="501",
            issue_number="1",
            title="Issue #1",
            store_date="2026-03-15 00:00:00",
            cover_date="2026-03-15 00:00:00",
        ),
    ]
    monkeypatch.setattr("app.enrichment.release_check.comicvine.list_issue_releases", lambda *a, **kw: updated_releases)
    _sync_release_events(db, series, "42", "fake-key", client=None)
    db.commit()

    assert db.query(SeriesReleaseEvent).count() == 1
    assert db.query(SeriesReleaseEvent).one().store_date == dt.date(2026, 3, 15)


def test_sync_release_events_marks_owned_book(db, monkeypatch):
    series = _make_series(db, library_type=LibraryType.COMICS)
    book = _make_book(
        db, series_id=series.id, library_id=series.library_id, number=1, external_ids={"comicvine_issue_id": 501}
    )
    db.flush()

    releases = [
        IssueRelease(
            external_id="501", issue_number="1", title="Owned", store_date="2026-01-01 00:00:00", cover_date=None
        ),
        IssueRelease(
            external_id="502", issue_number="2", title="Not owned", store_date="2026-01-01 00:00:00", cover_date=None
        ),
    ]
    monkeypatch.setattr("app.enrichment.release_check.comicvine.list_issue_releases", lambda *a, **kw: releases)

    _sync_release_events(db, series, "42", "fake-key", client=None)
    db.commit()

    by_external_id = {e.external_issue_id: e for e in db.query(SeriesReleaseEvent).all()}
    assert by_external_id["501"].owned_book_id == book.id
    assert by_external_id["502"].owned_book_id is None


def test_check_series_for_new_release_also_syncs_release_events(db, monkeypatch):
    series = _make_series(db, library_type=LibraryType.COMICS)
    _make_book(
        db, series_id=series.id, library_id=series.library_id, number=1, external_ids={"comicvine_volume_id": 42}
    )
    db.flush()

    monkeypatch.setattr("app.enrichment.release_check.comicvine.fetch_issue_count", lambda *a, **kw: 5)
    releases = [
        IssueRelease(
            external_id="999", issue_number="5", title="New", store_date="2026-06-01 00:00:00", cover_date=None
        )
    ]
    monkeypatch.setattr("app.enrichment.release_check.comicvine.list_issue_releases", lambda *a, **kw: releases)

    check_series_for_new_release(db, series, comicvine_api_key="fake-key")

    assert db.query(SeriesReleaseEvent).filter(SeriesReleaseEvent.external_issue_id == "999").count() == 1
