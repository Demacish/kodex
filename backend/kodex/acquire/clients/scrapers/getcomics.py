"""GetComics.org scraping (C12) — searches GetComics via FlareSolverr
(Cloudflare sits in front of it) and extracts direct download links.

Same caveat as kodex/acquire/clients/annas_archive.py: GetComics' actual markup
hasn't been checked against a live page in this environment (no network
access here) — _parse_results below is a best-effort placeholder that
needs verification against the real site before this is trusted in
production. Only _parse_results needs to change if the markup differs.

Guarded by a module-level CircuitBreaker (see kodex/acquire/clients/
circuit_breaker.py): GetComics scraping goes through FlareSolverr, and a
FlareSolverr instance that's down or mis-configured would otherwise get
hit with a fresh several-second solve attempt on every single search —
after a few consecutive failures this short-circuits with an immediate,
clear error instead of piling up slow, doomed requests.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

from kodex.acquire.clients.base import DownloadClientError
from kodex.acquire.clients.circuit_breaker import CircuitBreaker
from kodex.acquire.clients.flaresolverr import FlareSolverrClient

logger = logging.getLogger(__name__)

_RESULT_RE = re.compile(
    r'<a[^>]+class="[^"]*download-link[^"]*"[^>]+href="([^"]+)"[^>]*>\s*([^<]+?)\s*<', re.IGNORECASE
)

_breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=300.0)


@dataclass
class GetComicsResult:
    title: str
    download_url: str


def search(
    query: str, *, flaresolverr_url: str, client: httpx.Client | None = None, breaker: CircuitBreaker | None = None
) -> list[GetComicsResult]:
    breaker = breaker or _breaker
    if breaker.is_open:
        raise DownloadClientError(
            "GetComics-sökning är tillfälligt avstängd (för många fel i rad) — försök igen senare"
        )
    if not flaresolverr_url:
        raise DownloadClientError("FlareSolverr is not configured (FLARESOLVERR_URL missing)")

    solver = FlareSolverrClient(flaresolverr_url, client=client)
    try:
        html = solver.solve(f"https://getcomics.org/?s={query}")
    except DownloadClientError:
        breaker.record_failure()
        raise
    else:
        breaker.record_success()
        return _parse_results(html)
    finally:
        solver.close()


def _parse_results(html: str) -> list[GetComicsResult]:
    return [GetComicsResult(title=title.strip(), download_url=url) for url, title in _RESULT_RE.findall(html)]
