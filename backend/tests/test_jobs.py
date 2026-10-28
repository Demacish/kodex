"""Background jobs (kodex.jobs) against the real PostgreSQL: enqueueing,
a worker running them, results and errors, the status names the web
client knows, the queueing lock, periodic jobs, and the /jobs API."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import text

from app.auth import get_current_user, require_admin
from app.main import app
from app.models.enums import LibraryType
from app.models.library import Library
from app.models.user import User
from kodex.core.db import engine
from kodex.jobs import Queue, fetch_job, list_jobs
from kodex.jobs.registry import register

_QUEUE = "test-jobs"


def add_numbers(a: int, b: int = 0) -> dict:
    return {"sum": a + b}


def always_fails(reason: str) -> None:
    raise ValueError(reason)


register(add_numbers)
register(always_fails)


@pytest.fixture(autouse=True)
def _empty_job_tables():
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE procrastinate_jobs, procrastinate_events, procrastinate_periodic_defers, job_results CASCADE"
            )
        )


def _work() -> None:
    from kodex.jobs.worker import run

    run([_QUEUE], wait=False, install_signal_handlers=False)


def test_a_job_runs_and_its_result_is_kept():
    ref = Queue(_QUEUE).enqueue(add_numbers, 2, b=3)
    queued = fetch_job(ref.id)
    assert queued is not None and (queued.status, queued.args) == ("queued", {"a": 2, "b": 3})
    _work()
    job = fetch_job(ref.id)
    assert job is not None
    assert (job.status, job.result, job.error) == ("finished", {"sum": 5}, None)
    assert job.enqueued_at and job.started_at and job.ended_at


def test_a_failed_job_keeps_its_error():
    ref = Queue(_QUEUE).enqueue(always_fails, "the archive is unreadable")
    _work()
    job = fetch_job(ref.id)
    assert job is not None and job.status == "failed"
    assert job.error == "ValueError: the archive is unreadable"


def test_the_same_job_id_is_queued_once():
    first = Queue(_QUEUE).enqueue(add_numbers, 1, job_id="add-once")
    second = Queue(_QUEUE).enqueue(add_numbers, 1, job_id="add-once")
    assert first.id == second.id
    _work()
    assert Queue(_QUEUE).enqueue(add_numbers, 1, job_id="add-once").id != first.id  # done, so queued again


def test_jobs_are_queued_from_several_threads_at_once(monkeypatch):
    """The API's first requests come in on several threads (the compose
    smoke test scans three libraries in the same second)."""
    import threading

    import kodex.jobs.app as jobs_app

    monkeypatch.setattr(jobs_app, "_sync_app", None)  # restored, still open, afterwards
    start = threading.Barrier(6)
    ids: list[str] = []
    errors: list[BaseException] = []

    def enqueue(n: int) -> None:
        start.wait()
        try:
            ids.append(Queue(_QUEUE).enqueue(add_numbers, n).id)
        except BaseException as exc:  # noqa: BLE001 - every failure is the finding
            errors.append(exc)

    threads = [threading.Thread(target=enqueue, args=(n,)) for n in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if jobs_app._sync_app is not None:
        jobs_app._sync_app.close()
    assert errors == []
    assert len(set(ids)) == 6


def test_list_jobs_has_queued_and_recently_ended_ones():
    done = Queue(_QUEUE).enqueue(add_numbers, 1)
    _work()
    waiting = Queue(_QUEUE).enqueue(add_numbers, 2)
    assert [j.id for j in list_jobs()] == [waiting.id, done.id]
    assert [j.id for j in list_jobs(finished_within=dt.timedelta(0))] == [waiting.id]


def test_unknown_or_malformed_ids_are_not_found():
    assert fetch_job("999999") is None and fetch_job("abc") is None


def test_poll_libraries_scans_those_not_scanned_lately(db_session, monkeypatch):
    from kodex.jobs import periodic

    now = dt.datetime(2026, 10, 26, 12, tzinfo=dt.UTC)
    kind = LibraryType.COMICS
    stale = Library(name="Gammal", path="a", library_type=kind, last_scanned_at=now - dt.timedelta(hours=3))
    fresh = Library(name="Ny", path="b", library_type=kind, last_scanned_at=now - dt.timedelta(minutes=5))
    never = Library(name="Aldrig", path="c", library_type=kind)
    db_session.add_all([stale, fresh, never])
    db_session.commit()
    assert sorted(periodic.due_libraries(now, dt.timedelta(hours=1))) == sorted([stale.id, never.id])

    queued: list[tuple] = []

    class FakeQueue:
        def enqueue(self, func, *args, **kwargs):
            queued.append((func.__name__, args, kwargs.get("job_id")))

    monkeypatch.setattr("app.workers.queue.get_scan_queue", lambda: FakeQueue())
    monkeypatch.setattr("app.config.get_settings", lambda: type("S", (), {"rescan_interval_minutes": 60})())
    assert periodic.poll_libraries(int(now.timestamp())) == 2
    assert {q[2] for q in queued} == {f"scan-library-{stale.id}", f"scan-library-{never.id}"}
    monkeypatch.setattr("app.config.get_settings", lambda: type("S", (), {"rescan_interval_minutes": 0})())
    assert periodic.poll_libraries(int(now.timestamp())) == 0


def test_ended_jobs_are_removed_after_the_retention():
    from kodex.jobs.periodic import remove_old_jobs_before

    old = Queue(_QUEUE).enqueue(add_numbers, 1)
    _work()
    waiting = Queue(_QUEUE).enqueue(add_numbers, 2)
    assert remove_old_jobs_before(dt.datetime.now(dt.UTC) - dt.timedelta(days=1)) == 0
    assert remove_old_jobs_before(dt.datetime.now(dt.UTC) + dt.timedelta(minutes=1)) == 1
    assert fetch_job(old.id) is None and fetch_job(waiting.id) is not None


def test_job_status_api(api):
    client, _ = api
    ref = Queue(_QUEUE).enqueue(add_numbers, 4, b=5)
    _work()
    assert client.get(f"/jobs/{ref.id}").json() == {"id": ref.id, "status": "finished", "result": {"sum": 9}}
    assert client.get("/jobs/123456789").status_code == 404
    ours = next(job for job in client.get("/jobs").json() if job["id"] == ref.id)
    assert (ours["label"], ours["queue"], ours["status"]) == ("add_numbers", _QUEUE, "finished")


def test_job_status_requires_admin(api):
    client, _ = api
    non_admin = User(id=2, oidc_subject="non-admin-sub", username="reader", is_admin=False)
    app.dependency_overrides[get_current_user] = lambda: non_admin
    del app.dependency_overrides[require_admin]
    assert client.get("/jobs/1").status_code == 403
