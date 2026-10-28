"""Best-effort cover-image lookup for AI-suggested titles — see
recommendations.py's generate_recommendations_for_user. A suggestion is
never something the user owns, so there's no local cover to show; this
does a lightweight provider search per suggestion and grabs whatever
thumbnail comes back first, same providers app/enrichment/engine.py
already uses per media type (Comic Vine for comics/series, AniList for
manga, Open Library — falling back to Google Books — for ebooks).

Deliberately never blocks the request it's called from: every path here
either returns quickly or gives up and returns None, and Comic Vine calls
use the rate limiter's try_acquire() (non-blocking) instead of the normal
acquire() app/enrichment/comicvine.py uses — that one sleeps until quota
frees up, correct for a background enrichment job but wrong for a
synchronous "Fler förslag" click sitting in front of a real user.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.config import get_settings
from app.enrichment import anilist, google_books, open_library
from app.enrichment.ratelimit import comicvine_limiter
from app.models.enums import RequestMediaType

logger = logging.getLogger(__name__)

_COMICVINE_SEARCH_URL = "https://comicvine.gamespot.com/api/search/"
_TIMEOUT = httpx.Timeout(5.0)
# I/O-bound network calls, not CPU-bound — more workers than CPU cores is
# fine and is the point (see fetch_cover_urls' own docstring).
_MAX_WORKERS = 6


def _comicvine_cover(title: str, api_key: str) -> str | None:
    if not api_key or not comicvine_limiter.try_acquire():
        return None
    try:
        response = httpx.get(
            _COMICVINE_SEARCH_URL,
            params={
                "api_key": api_key,
                "format": "json",
                "query": title,
                "resources": "volume",
                "limit": 1,
                "field_list": "image",
            },
            # Comic Vine 403s anonymous/default-user-agent requests as bot
            # traffic — app/enrichment/http.py's get_client() already sets
            # this for the rest of the app's Comic Vine calls; this
            # function uses a raw httpx.get() instead (see this module's
            # own docstring for why: get_client() has nothing to do with
            # it, this is about NOT reusing comicvine.py's search(), which
            # calls the BLOCKING rate-limiter acquire() internally), so it
            # has to set the header itself too. Found 2026-09-21 — every
            # suggestion's comic cover was silently None because of this,
            # reported as "just placeholder images."
            headers={"User-Agent": get_settings().enrichment_user_agent},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        if not results:
            return None
        return (results[0].get("image") or {}).get("thumb_url")
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("Comic Vine cover lookup failed for %r: %s", title, exc)
        return None


def _provider_cover(
    title: str, media_type_guess: RequestMediaType | None, *, comicvine_api_key: str, google_books_api_key: str
) -> str | None:
    try:
        if media_type_guess == RequestMediaType.MANGA:
            candidates = anilist.search(title)
            return candidates[0].thumbnail_url if candidates else None
        if media_type_guess == RequestMediaType.EBOOK:
            candidates = open_library.search(title) or google_books.search(title, google_books_api_key)
            return candidates[0].thumbnail_url if candidates else None
        # None or "series" — comics is this app's primary/default media
        # type, and Comic Vine is the only cover source for it here.
        return _comicvine_cover(title, comicvine_api_key)
    except Exception as exc:  # noqa: BLE001 — a broken lookup must never break the whole recommendation batch
        logger.debug("Cover lookup failed for %r: %s", title, exc)
        return None


def fetch_cover_urls(
    suggestions: list[tuple[str, RequestMediaType | None]], *, comicvine_api_key: str, google_books_api_key: str
) -> list[str | None]:
    """One thumbnail URL (or None) per (title, media_type_guess) pair, in
    the same order — run in parallel across a small thread pool rather
    than one at a time, since a batch of up to 20 sequential few-hundred-
    ms provider searches would make "Fler förslag" visibly slow otherwise.
    """
    if not suggestions:
        return []
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(suggestions))) as pool:
        return list(
            pool.map(
                lambda item: _provider_cover(
                    item[0], item[1], comicvine_api_key=comicvine_api_key, google_books_api_key=google_books_api_key
                ),
                suggestions,
            )
        )
