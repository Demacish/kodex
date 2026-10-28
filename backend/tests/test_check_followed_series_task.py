"""Tests for app.workers.tasks.check_followed_series_task's notification
logic (A1: manual follow/unfollow + notify on new release) — specifically
that notify_new_release only fires on an actual False→True transition of
Series.new_release_available, never on a run that finds it still True (or
still False). check_series_for_new_release's own behavior is covered by
test_release_check.py; this file only exercises the task-level wrapper
that decides *when* to notify.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

import app.workers.tasks as tasks
from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.models.metadata import BookMetadata
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


def _make_followed_series(db, *, new_release_available: bool = False) -> int:
    """Returns the new series' id (a plain int) rather than the ORM object
    itself — the task under test commits (which expires all of `db`'s
    tracked objects) and then closes `db` in its finally block. Whether an
    already-expired object's attribute is still safely readable afterwards
    depends on incidental reload timing inside the task (e.g. a series
    that's already new_release_available=True is skipped by the task's own
    `not was_available and ...` short-circuit and never gets reloaded) —
    not something a test should depend on. A plain id sidesteps all of it.
    """
    library = Library(name="Test", path="test", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    series = Series(
        library_id=library.id,
        title="Test Series",
        sort_title="Test Series",
        path="Test Series",
        is_following=True,
        new_release_available=new_release_available,
    )
    db.add(series)
    db.flush()
    book = Book(
        library_id=library.id,
        series_id=series.id,
        file_path="1.cbz",
        file_format=BookFormat.CBZ,
        file_size=1,
        file_mtime=0.0,
        number=1,
    )
    db.add(book)
    db.flush()
    db.add(
        BookMetadata(book_id=book.id, title="Issue 1", sort_title="Issue 1", external_ids={"comicvine_volume_id": 42})
    )
    db.commit()
    return series.id


def _reload_new_release_available(db, series_id: int) -> bool:
    # Same reasoning as _make_followed_series's docstring: read the
    # actually-persisted value through a fresh session on the same
    # still-open in-memory-sqlite engine, rather than the (by now closed
    # and possibly-expired) `db` session the task ran against.
    session = sessionmaker(bind=db.get_bind(), future=True)()
    try:
        return bool(session.get(Series, series_id).new_release_available)
    finally:
        session.close()


def _run_task(db, monkeypatch, *, notify_calls: list, published_count: int):
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(tasks, "get_settings", lambda: type("S", (), {"comicvine_api_key": "fake-key"})())
    monkeypatch.setattr("app.enrichment.release_check.comicvine.fetch_issue_count", lambda *a, **kw: published_count)
    monkeypatch.setattr("app.enrichment.release_check.comicvine.list_issue_releases", lambda *a, **kw: [])
    monkeypatch.setattr(tasks, "notify_new_release", lambda series, *, settings: notify_calls.append(series.id))
    return tasks.check_followed_series_task()


def test_notifies_on_false_to_true_transition(db, monkeypatch):
    series_id = _make_followed_series(db, new_release_available=False)
    notify_calls: list = []

    result = _run_task(db, monkeypatch, notify_calls=notify_calls, published_count=5)

    assert result["series_newly_available"] == 1
    assert notify_calls == [series_id]
    assert _reload_new_release_available(db, series_id) is True


def test_does_not_renotify_when_already_true(db, monkeypatch):
    series_id = _make_followed_series(db, new_release_available=True)
    notify_calls: list = []

    result = _run_task(db, monkeypatch, notify_calls=notify_calls, published_count=5)

    assert result["series_newly_available"] == 0
    assert notify_calls == []
    assert _reload_new_release_available(db, series_id) is True


def test_does_not_notify_when_still_no_new_release(db, monkeypatch):
    _make_followed_series(db, new_release_available=False)
    notify_calls: list = []

    result = _run_task(db, monkeypatch, notify_calls=notify_calls, published_count=1)

    assert result["series_newly_available"] == 0
    assert notify_calls == []
