"""Anna's Archive (C13) — deliberately interactive-only source, per an
explicit choice made when this batch was planned (not auto-download like
qBittorrent/SABnzbd/Prowlarr): every search hit here is always routed to
manual retrieval, never fetched automatically. See kodex/acquire/clients/base.py's
module docstring for the general "code/schema only, no real host reachable
yet" caveat that applies to this whole package.

Anna's Archive has no public search API — this module scrapes its search
results HTML. The exact markup below is a best-effort guess based on
Anna's Archive's known public URL scheme (/search?q=..., result links at
/md5/<hash>) and has NOT been verified against a live page in this
environment (no network access here) — same "needs verification against
the real thing before trusting it in production" caveat this project
already carries for C14's LOCG/Goodreads CSV column names. If the real
markup differs, only _parse_results below needs to change.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

from kodex.acquire.clients.base import DownloadClientError

logger = logging.getLogger(__name__)

_RESULT_RE = re.compile(r'href="/md5/([a-f0-9]{32})"[^>]*>\s*(?:<[^>]+>\s*)*([^<]+?)\s*<', re.IGNORECASE)


def parse_mirrors(raw: str) -> list[str]:
    """Splits settings.annas_archive_mirrors' comma-separated string into
    a clean list of base URLs, in the configured try-order.
    """
    return [mirror.strip().rstrip("/") for mirror in raw.split(",") if mirror.strip()]


@dataclass
class AnnasArchiveResult:
    title: str
    detail_url: str
    mirror: str


def search(query: str, *, mirrors: list[str], client: httpx.Client | None = None) -> list[AnnasArchiveResult]:
    """Tries each mirror in order, returns the first one that answers
    successfully — Anna's Archive mirrors rotate/go down often (see
    settings.annas_archive_mirrors' own docstring), so a single mirror
    failing isn't treated as the whole search failing.
    """
    if not mirrors:
        raise DownloadClientError("Anna's Archive is not configured (ANNAS_ARCHIVE_MIRRORS is empty)")

    owned_client = client or httpx.Client(timeout=30.0)
    last_error: Exception | None = None
    try:
        for mirror in mirrors:
            try:
                response = owned_client.get(f"{mirror}/search", params={"q": query})
                response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("Anna's Archive mirror %s failed: %s", mirror, exc)
                last_error = exc
                continue
            return _parse_results(response.text, mirror)
    finally:
        if client is None:
            owned_client.close()

    raise DownloadClientError(f"All Anna's Archive mirrors failed: {last_error}")


def _parse_results(html: str, mirror: str) -> list[AnnasArchiveResult]:
    results = []
    seen_hashes: set[str] = set()
    for md5_hash, title in _RESULT_RE.findall(html):
        if md5_hash in seen_hashes:
            continue
        seen_hashes.add(md5_hash)
        results.append(AnnasArchiveResult(title=title.strip(), detail_url=f"{mirror}/md5/{md5_hash}", mirror=mirror))
    return results
