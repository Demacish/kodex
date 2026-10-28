"""Background jobs on Procrastinate (docs/decisions/0006-jobs.md): the
queue interface the rest of Kodex enqueues through, the job overview,
periodic jobs and the worker.

Jobs live in PostgreSQL (Procrastinate's tables, created by migration
0005), so there is no Redis, and periodic jobs are deduplicated in the
database however many workers run. The rest of Kodex only sees
``Queue.enqueue(function, *args)``, ``fetch_job`` and ``list_jobs``, so
Procrastinate can be replaced behind them (pgqueuer is the named fallback).
"""

from kodex.jobs.queue import (
    DELIVERY_QUEUE_NAME,
    DOWNLOAD_QUEUE_NAME,
    ENRICHMENT_QUEUE_NAME,
    FULLTEXT_QUEUE_NAME,
    PANEL_QUEUE_NAME,
    QUEUE_NAMES,
    SCAN_QUEUE_NAME,
    JobInfo,
    JobRef,
    Queue,
    fetch_job,
    list_jobs,
)

__all__ = [
    "DELIVERY_QUEUE_NAME", "DOWNLOAD_QUEUE_NAME", "ENRICHMENT_QUEUE_NAME", "FULLTEXT_QUEUE_NAME", "PANEL_QUEUE_NAME",
    "QUEUE_NAMES", "SCAN_QUEUE_NAME", "JobInfo", "JobRef", "Queue", "fetch_job", "list_jobs",
]  # fmt: skip
