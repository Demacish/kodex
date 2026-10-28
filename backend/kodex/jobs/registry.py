"""The task functions in app/workers/tasks.py as Procrastinate tasks, each
run through a wrapper that stores its result (or error) in job_results.
Tasks are registered under their function's name, which is also what the
job overview labels them by."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

from procrastinate import JobContext

from kodex.jobs.app import app

logger = logging.getLogger(__name__)

_registered: dict[str, Callable[..., Any]] = {}
_loaded = False
_lock = threading.Lock()


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def store_result(job_id: int, result: Any, error: str | None) -> None:
    from sqlalchemy.dialects.postgresql import insert

    from kodex.core.db import SessionLocal
    from kodex.jobs.models import JobResult

    with SessionLocal() as db:
        values = {"job_id": job_id, "result": _json_safe(result), "error": error}
        db.execute(insert(JobResult).values(**values).on_conflict_do_update(index_elements=["job_id"], set_=values))
        db.commit()


def register(func: Callable[..., Any]) -> None:
    name = func.__name__

    def run(context: JobContext, /, **kwargs: Any) -> Any:
        job_id = context.job.id
        try:
            result = func(**kwargs)
        except Exception as exc:
            if job_id is not None:
                store_result(job_id, None, f"{type(exc).__name__}: {exc}")
            raise
        if job_id is not None:
            store_result(job_id, result, None)
        return result

    run.__name__ = run.__qualname__ = name
    app.task(name=name, pass_context=True)(run)
    _registered[name] = func


def load_tasks() -> dict[str, Callable[..., Any]]:
    """Registers every ``*_task`` function of app/workers/tasks.py, and
    kodex's own, once."""
    global _loaded
    with _lock:
        # A flag of its own, not an empty registry: tasks registered one by
        # one (the tests' own) mustn't keep the real ones out.
        if not _loaded:
            from app.workers import tasks as v1

            for name, func in vars(v1).items():
                if name.endswith("_task") and callable(func) and getattr(func, "__module__", "") == v1.__name__:
                    register(func)
            from kodex.acquire import pipeline

            for func in (pipeline.acquire_request_task, pipeline.import_download_task):
                register(func)
            _loaded = True
    return _registered
