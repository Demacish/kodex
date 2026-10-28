"""Prowlarr indexer proxy (C11) — searches Prowlarr's aggregated indexers
and normalizes results into a client-agnostic shape. See kodex/acquire/clients/
base.py's module docstring: Prowlarr, like qBittorrent/SABnzbd, is never
actually reachable in this deployment yet — code/schema only.

Prowlarr's own /api/v1/search returns raw per-indexer fields (downloadUrl
vs magnetUrl, protocol as "torrent"/"usenet", etc.) — this module is the
one place that shape is parsed, so kodex/acquire/downloads.py's search
endpoint and C10's create-download pipeline never need to know about it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.models.enums import DownloadClientType
from kodex.acquire.clients.base import DownloadClientError

logger = logging.getLogger(__name__)

# Torznab category 7020 = Comics, 7030 = Comics/Digital.
COMIC_CATEGORIES = "7020,7030"

# Prowlarr's own "protocol" string -> which client handles it. Shared
# between kodex/acquire/downloads.py (POST /downloads/from-search) and
# kodex/acquire/requests.py (the Batch-C Request auto-download tie-in).
PROTOCOL_TO_CLIENT = {"torrent": DownloadClientType.QBITTORRENT, "usenet": DownloadClientType.SABNZBD}


@dataclass
class ProwlarrResult:
    title: str
    download_url: str
    protocol: str  # "torrent" or "usenet" — see DownloadClientType mapping in routes/downloads.py
    indexer: str
    size: int | None
    publish_date: str | None


def search(
    query: str, *, base_url: str, api_key: str, categories: str = COMIC_CATEGORIES, client: httpx.Client | None = None
) -> list[ProwlarrResult]:
    if not base_url or not api_key:
        raise DownloadClientError("Prowlarr is not configured (PROWLARR_URL/PROWLARR_API_KEY missing)")

    owned_client = client or httpx.Client(timeout=30.0)
    try:
        response = owned_client.get(
            f"{base_url.rstrip('/')}/api/v1/search",
            params={"query": query, "categories": categories},
            headers={"X-Api-Key": api_key},
        )
        response.raise_for_status()
        raw_results = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise DownloadClientError(f"Prowlarr search failed: {exc}") from exc
    finally:
        if client is None:
            owned_client.close()

    results = []
    for item in raw_results:
        download_url = item.get("magnetUrl") or item.get("downloadUrl")
        protocol = item.get("protocol")
        title = item.get("title")
        if not download_url or protocol not in ("torrent", "usenet") or not title:
            logger.debug("Skipping unusable Prowlarr result: %r", item)
            continue
        results.append(
            ProwlarrResult(
                title=title,
                download_url=download_url,
                protocol=protocol,
                indexer=item.get("indexer", "unknown"),
                size=item.get("size"),
                publish_date=item.get("publishDate"),
            )
        )
    return results
