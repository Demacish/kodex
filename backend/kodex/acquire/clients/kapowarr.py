"""Kapowarr client (requested 2026-09-21) — a full comic library manager
running on a separate, user-managed host, same overall shape as
mylar3.py (see that module's and app/config.py's mylar3_url docstrings):
Kodex only ever tells it to start tracking/searching a Comic Vine
volume; the finished file arrives back into Kodex later via that host's
own upload script hitting the existing B7 endpoint.

Based on Kapowarr's documented REST API (https://casvt.github.io/
Kapowarr/) — NOT verified against a live instance from this environment
(no network access here, same caveat this project already carries for
Anna's Archive/GetComics' scraping modules and mylar3.py above). JSON
REST API, `X-Api-Key` header auth, comicvine ids passed as
"cv:{id}" per Kapowarr's own id-prefixing convention.
"""

from __future__ import annotations

import httpx

from app.enrichment.http import get_client
from kodex.acquire.clients.base import DownloadClientError


def add_volume(
    comicvine_id: str, *, base_url: str, api_key: str, root_folder_id: str, client: httpx.Client | None = None
) -> None:
    """Adds (and, by default, starts monitoring/searching for) a volume —
    root_folder_id is one of Kapowarr's OWN configured library roots
    (see app/config.py's kapowarr_root_folder_id docstring for why
    there's no sane default to pick automatically, and why it's a plain
    string parsed to int here rather than an int setting).
    """
    if not base_url or not api_key:
        raise DownloadClientError("Kapowarr is not configured (KAPOWARR_URL/KAPOWARR_API_KEY missing)")
    if not root_folder_id:
        raise DownloadClientError("Kapowarr is not configured (KAPOWARR_ROOT_FOLDER_ID missing)")
    try:
        root_folder_id_int = int(root_folder_id)
    except ValueError as exc:
        raise DownloadClientError(f"KAPOWARR_ROOT_FOLDER_ID must be a plain integer, got {root_folder_id!r}") from exc

    owned_client = client or get_client()
    try:
        response = owned_client.post(
            f"{base_url.rstrip('/')}/api/volumes",
            params={"api_key": api_key},
            json={"comicvine_id": f"cv:{comicvine_id}", "root_folder_id": root_folder_id_int, "monitor": True},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise DownloadClientError(f"Kapowarr add-volume request failed: {exc}") from exc
    finally:
        if client is None:
            owned_client.close()
