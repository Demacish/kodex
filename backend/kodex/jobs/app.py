"""The Procrastinate app the tasks are registered on and the worker runs
(async connector), and a second app on a synchronous connector for
enqueueing from synchronous code (the API's routes, tasks enqueueing
tasks)."""

from __future__ import annotations

import threading

import procrastinate


def conninfo() -> str:
    """The database URL as psycopg wants it (without SQLAlchemy's
    ``+psycopg`` driver suffix)."""
    from app.config import get_settings

    url = get_settings().database_url
    scheme, _, rest = url.partition("://")
    return f"{scheme.split('+')[0]}://{rest}"


app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=conninfo()))


_sync_app: procrastinate.App | None = None
_sync_lock = threading.Lock()


def sync_app() -> procrastinate.App:
    """An app on a synchronous connector, only for deferring jobs by task
    name (see kodex.jobs.queue); it has no tasks of its own. Made once,
    under a lock: the API's first requests come in on several threads at
    once (three libraries scanned in the same second made a 500)."""
    global _sync_app
    with _sync_lock:
        if _sync_app is None:
            from kodex.jobs.registry import load_tasks

            load_tasks()
            deferring = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=conninfo()))
            deferring.open()
            _sync_app = deferring
        return _sync_app
