"""Syncing this server's reading progress with a central Kodex server.

Set PROGRESS_SYNC_URL (the central server's <backend>/kosync), plus the
username and OPDS token of the account to sync as there, on every server
except the central one. This server then:

- pushes each saved position there in the background (an RQ job, so a slow
  or unreachable central server never slows down the reader), and
- pulls the central position when a book is opened (GET
  /books/{id}/progress) and takes it if it's further — see
  app/progress/sync.py's rules.

It talks the same kosync protocol KOReader does (app/api/routes/
kosync.py), keyed by the book's content_hash, so the same file on two
servers is the same book. Every user of this server syncs as that one
central account: meant for a household's secondary servers (a NAS, a
Windows PC), not for multi-user ones.
"""

from __future__ import annotations

import hashlib
import logging

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Marks requests from another Kodex server, so the central one answers
# with percentage-only EPUB positions too (KOReader can't use those).
KODEX_CLIENT_HEADER = "x-kodex-client"
_TIMEOUT_SECONDS = 3.0
_DEVICE = "Kodex"


def is_enabled(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(settings.progress_sync_url and settings.progress_sync_username and settings.progress_sync_token)


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "x-auth-user": settings.progress_sync_username,
        "x-auth-key": hashlib.md5(settings.progress_sync_token.encode()).hexdigest(),
        "accept": "application/vnd.koreader.v1+json",
        KODEX_CLIENT_HEADER: "1",
    }


def _url(settings: Settings, path: str) -> str:
    return settings.progress_sync_url.rstrip("/") + path


def device_id(settings: Settings) -> str:
    """Identifies this server to the central one (shown as the device)."""
    return settings.progress_sync_device_name or "kodex-server"


def push(document: str, *, progress: str | None, percentage: float, reset: bool) -> None:
    settings = get_settings()
    response = httpx.put(
        _url(settings, "/syncs/progress"),
        headers=_headers(settings),
        json={
            "document": document,
            "progress": progress,
            "percentage": percentage,
            "device": _DEVICE,
            "device_id": device_id(settings),
            "kodex_reset": reset,
        },
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()


def pull(document: str) -> dict | None:
    """The central server's position for a document, or None (none stored,
    or the central server couldn't be reached — never raises)."""
    settings = get_settings()
    try:
        response = httpx.get(
            _url(settings, f"/syncs/progress/{document}"), headers=_headers(settings), timeout=_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Could not pull progress for %s from the central server: %s", document, exc)
        return None
    if not isinstance(body, dict) or "percentage" not in body:
        return None
    return body


def enqueue_upstream_push(book_id: int, user_id: int, *, reset: bool = False) -> None:
    """Queues a push of this user's position on this book. A no-op when
    syncing isn't configured; never raises (a Redis hiccup must not fail
    the progress save that triggered it)."""
    if not is_enabled():
        return
    from app.workers.queue import get_delivery_queue
    from app.workers.tasks import push_progress_upstream_task

    try:
        get_delivery_queue().enqueue(push_progress_upstream_task, book_id, user_id, reset, job_timeout="1m")
    except Exception:
        logger.exception("Could not queue a progress push for book %s", book_id)
