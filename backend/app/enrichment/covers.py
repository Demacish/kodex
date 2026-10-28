from __future__ import annotations

import logging
from pathlib import Path

import httpx

from app.config import get_settings
from kodex.core import outbound

logger = logging.getLogger(__name__)


def download_cover(url: str, book_id: int, *, client: httpx.Client | None = None) -> str | None:
    """Downloads a cover image and caches it under settings.covers_dir,
    returning the path BookMetadata.cover_path should store (relative to
    covers_dir, so the deployment can move that directory without a
    database update).
    """
    settings = get_settings()
    # The address comes from a provider's data: never to this machine or its network.
    owned_client = client or outbound.client(timeout=settings.enrichment_http_timeout_seconds,
                                             headers={"User-Agent": settings.enrichment_user_agent})  # fmt: skip
    try:
        response = owned_client.get(url, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Cover download failed for book %s (%s): %s", book_id, url, exc)
        return None
    finally:
        if client is None:
            owned_client.close()

    suffix = Path(url.split("?")[0]).suffix or ".jpg"
    relative_path = f"{book_id}{suffix}"

    dest = settings.covers_dir / relative_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(response.content)

    return relative_path
