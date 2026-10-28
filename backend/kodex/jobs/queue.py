"""Enqueueing and looking up jobs.

``Queue(name).enqueue(function, *args, job_id=...)`` keeps the shape of
v1's RQ calls: positional arguments become the task's keyword arguments
(Procrastinate stores them as JSON), and ``job_id`` becomes a queueing lock
so the same job isn't queued twice. RQ's per-job timeout has no equivalent
and is ignored. Statuses are reported with RQ's names, which the web
client knows.
"""

from __future__ import annotations

import datetime as dt
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

SCAN_QUEUE_NAME = "scanning"
ENRICHMENT_QUEUE_NAME = "enrichment"
FULLTEXT_QUEUE_NAME = "fulltext"
DELIVERY_QUEUE_NAME = "delivery"
PANEL_QUEUE_NAME = "panels"
DOWNLOAD_QUEUE_NAME = "download"
QUEUE_NAMES = (
    SCAN_QUEUE_NAME, ENRICHMENT_QUEUE_NAME, FULLTEXT_QUEUE_NAME, DELIVERY_QUEUE_NAME, PANEL_QUEUE_NAME,
    DOWNLOAD_QUEUE_NAME,
)  # fmt: skip

_STATUS = {"todo": "queued", "doing": "started", "succeeded": "finished", "failed": "failed",
           "cancelled": "canceled", "aborting": "stopped", "aborted": "stopped"}  # fmt: skip


@dataclass
class JobRef:
    id: str


@dataclass
class JobInfo:
    id: str
    queue: str
    task_name: str
    status: str
    args: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: str | None = None
    enqueued_at: dt.datetime | None = None
    started_at: dt.datetime | None = None
    ended_at: dt.datetime | None = None


class Queue:
    def __init__(self, name: str) -> None:
        self.name = name

    def enqueue(self, func: Callable[..., Any], *args: Any, job_id: str | None = None,
                job_timeout: str | int | None = None, **kwargs: Any) -> JobRef:  # fmt: skip
        from procrastinate.exceptions import AlreadyEnqueued
        from procrastinate.tasks import configure_task

        from kodex.jobs.app import app as tasks_app
        from kodex.jobs.app import sync_app

        deferring = sync_app()
        if func.__name__ not in tasks_app.tasks:
            raise LookupError(f"{func.__name__} is not a registered task")
        arguments = dict(inspect.signature(func).bind(*args, **kwargs).arguments)
        # Deferred by name through the synchronous app's job manager: a Task
        # object belongs to the app it was registered on, whose connector is
        # async and open only in the worker.
        options: dict[str, Any] = {"queue": self.name}
        if job_id:
            options["queueing_lock"] = job_id
        deferrer = configure_task(name=func.__name__, job_manager=deferring.job_manager, **options)
        try:
            return JobRef(str(deferrer.defer(**arguments)))
        except AlreadyEnqueued:
            existing = _queued_with_lock(job_id or "")
            return JobRef(existing or job_id or "")


def _engine() -> Any:
    from kodex.core.db import engine

    return engine


def _queued_with_lock(lock: str) -> str | None:
    with _engine().connect() as connection:
        row = connection.execute(
            text("SELECT id FROM procrastinate_jobs WHERE queueing_lock = :lock AND status = 'todo' ORDER BY id DESC"),
            {"lock": lock},
        ).first()
    return str(row[0]) if row else None


_JOBS_SQL = """
SELECT j.id, j.queue_name, j.task_name, j.status::text AS status, j.args, j.scheduled_at,
       r.result, r.error,
       min(e.at) FILTER (WHERE e.type = 'deferred') AS enqueued_at,
       max(e.at) FILTER (WHERE e.type = 'started') AS started_at,
       max(e.at) FILTER (WHERE e.type IN ('succeeded', 'failed', 'cancelled', 'aborted')) AS ended_at
FROM procrastinate_jobs j
LEFT JOIN job_results r ON r.job_id = j.id
LEFT JOIN procrastinate_events e ON e.job_id = j.id
{where}
GROUP BY j.id, r.job_id
ORDER BY j.id DESC
LIMIT :limit
"""


def _info(row: Any) -> JobInfo:
    status = _STATUS.get(row.status, row.status)
    if status == "queued" and row.scheduled_at is not None and row.scheduled_at > dt.datetime.now(dt.UTC):
        status = "scheduled"
    return JobInfo(id=str(row.id), queue=row.queue_name, task_name=row.task_name, status=status, args=row.args or {},
                   result=row.result, error=row.error, enqueued_at=row.enqueued_at, started_at=row.started_at,
                   ended_at=row.ended_at)  # fmt: skip


def fetch_job(job_id: str) -> JobInfo | None:
    if not job_id.isdigit():
        return None
    with _engine().connect() as connection:
        row = connection.execute(
            text(_JOBS_SQL.format(where="WHERE j.id = :id")), {"id": int(job_id), "limit": 1}
        ).first()
    return _info(row) if row else None


def list_jobs(*, finished_within: dt.timedelta = dt.timedelta(days=1), limit: int = 200) -> list[JobInfo]:
    """Queued and running jobs, and those that ended within ``finished_within``."""
    since = dt.datetime.now(dt.UTC) - finished_within
    where = (
        "WHERE j.status IN ('todo', 'doing') OR j.id IN "
        "(SELECT job_id FROM procrastinate_events WHERE at >= :since AND type IN ('succeeded', 'failed', 'cancelled', 'aborted'))"
    )
    with _engine().connect() as connection:
        rows = connection.execute(text(_JOBS_SQL.format(where=where)), {"since": since, "limit": limit}).all()
    return [_info(row) for row in rows]
