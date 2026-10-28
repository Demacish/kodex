"""Mylar3 client (requested 2026-09-21) — a full comic library manager
running on a separate, user-managed host (see app/config.py's mylar3_url
docstring for the overall shape: Kodex only ever tells it to start
tracking/searching a Comic Vine volume, the finished file arrives back
into Kodex later via that same host's own upload script hitting the
existing B7 endpoint).

Based on Mylar3's documented API shape (https://github.com/mylar3/mylar3/
wiki/api) — NOT verified against a live instance from this environment
(no network access here, same caveat this project already carries for
Anna's Archive/GetComics' scraping modules). Query-string API:
GET {base_url}/api?apikey={key}&cmd={cmd}&...
"""

from __future__ import annotations

import logging

import httpx

from app.enrichment.http import get_client
from kodex.acquire.clients.base import DownloadClientError

logger = logging.getLogger(__name__)


def add_comic(comicvine_id: str, *, base_url: str, api_key: str, client: httpx.Client | None = None) -> None:
    """Tells Mylar3 to start tracking this Comic Vine volume — it does its
    own search/download/organize from here using whatever indexers/
    download clients are configured on the Mylar3 side, entirely outside
    Kodex's visibility.
    """
    if not base_url or not api_key:
        raise DownloadClientError("Mylar3 is not configured (MYLAR3_URL/MYLAR3_API_KEY missing)")

    owned_client = client or get_client()
    try:
        response = owned_client.get(
            f"{base_url.rstrip('/')}/api",
            params={"apikey": api_key, "cmd": "addComic", "id": comicvine_id},
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise DownloadClientError(f"Mylar3 addComic request failed: {exc}") from exc
    finally:
        if client is None:
            owned_client.close()

    if isinstance(body, dict) and body.get("success") is False:
        raise DownloadClientError(f"Mylar3 rejected the comic: {body.get('error', 'unknown error')}")
