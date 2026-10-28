"""v1's queue accessors, now on kodex.jobs (Procrastinate, in PostgreSQL).
Each queue keeps its own name so a heavy run of one kind (a library-wide
enrichment, panel detection) doesn't block the others in the job view."""

from __future__ import annotations

from functools import lru_cache

from kodex.jobs import (
    DELIVERY_QUEUE_NAME,
    DOWNLOAD_QUEUE_NAME,
    ENRICHMENT_QUEUE_NAME,
    FULLTEXT_QUEUE_NAME,
    PANEL_QUEUE_NAME,
    QUEUE_NAMES,
    SCAN_QUEUE_NAME,
    JobInfo,
    Queue,
)
from kodex.jobs import fetch_job as _fetch_job

ALL_QUEUE_NAMES = QUEUE_NAMES

__all__ = [
    "ALL_QUEUE_NAMES", "DELIVERY_QUEUE_NAME", "DOWNLOAD_QUEUE_NAME", "ENRICHMENT_QUEUE_NAME", "FULLTEXT_QUEUE_NAME",
    "PANEL_QUEUE_NAME", "SCAN_QUEUE_NAME", "fetch_job", "get_delivery_queue", "get_download_queue",
    "get_enrichment_queue", "get_fulltext_queue", "get_panel_queue", "get_scan_queue",
]  # fmt: skip


@lru_cache
def get_scan_queue() -> Queue:
    return Queue(SCAN_QUEUE_NAME)


@lru_cache
def get_enrichment_queue() -> Queue:
    return Queue(ENRICHMENT_QUEUE_NAME)


@lru_cache
def get_fulltext_queue() -> Queue:
    return Queue(FULLTEXT_QUEUE_NAME)


@lru_cache
def get_delivery_queue() -> Queue:
    return Queue(DELIVERY_QUEUE_NAME)


@lru_cache
def get_panel_queue() -> Queue:
    return Queue(PANEL_QUEUE_NAME)


@lru_cache
def get_download_queue() -> Queue:
    return Queue(DOWNLOAD_QUEUE_NAME)


def fetch_job(job_id: str) -> JobInfo | None:
    return _fetch_job(job_id)
