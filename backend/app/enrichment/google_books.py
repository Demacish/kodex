"""Google Books provider — a fallback for EBOOKS when Open Library has
nothing useful. Works anonymously but Google's anonymous quota turned out
(2026-09-17) to be exhausted almost immediately in practice - every single
anonymous call during a full-library run got 429. An optional free API key
(settings.google_books_api_key) gets a much higher quota; pass it through
when available.
"""

from __future__ import annotations

import logging

import httpx

from app.enrichment.base import Candidate, EnrichmentResult
from app.enrichment.http import get_client
from app.enrichment.text import best_match, strip_html

logger = logging.getLogger(__name__)

BASE_URL = "https://www.googleapis.com/books/v1/volumes"

# Google returns several sizes when available; largest-first so the
# downloaded, permanently-cached cover (see covers.py) isn't stuck at
# "thumbnail" (the second-smallest) forever - confirmed 2026-09-17 that
# books offering all six sizes were only ever getting the small one,
# which is what made covers look pixelated once actually displayed at
# full size on a book's page.
_COVER_SIZE_PREFERENCE = ("extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail")


def _best_cover_url(image_links: dict) -> str | None:
    for size in _COVER_SIZE_PREFERENCE:
        if url := image_links.get(size):
            return url
    return None


def search(query: str, api_key: str = "", *, client: httpx.Client | None = None) -> list[Candidate]:
    owned_client = client or get_client()
    params = {"q": query, "maxResults": 10}
    if api_key:
        params["key"] = api_key
    try:
        response = owned_client.get(BASE_URL, params=params)
        response.raise_for_status()
        items = response.json().get("items", [])
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Google Books search failed for %r: %s", query, exc)
        return []
    finally:
        if client is None:
            owned_client.close()

    candidates = []
    for item in items:
        info = item.get("volumeInfo", {})
        published_date = info.get("publishedDate", "")
        year = int(published_date[:4]) if published_date[:4].isdigit() else None
        candidates.append(
            Candidate(
                external_id=item["id"],
                title=info.get("title") or "(namnlös)",
                year=year,
                thumbnail_url=(info.get("imageLinks") or {}).get("thumbnail"),
                subtitle=", ".join(info.get("authors", [])[:2]) or None,
            )
        )
    return candidates


def fetch_details(
    external_id: str, api_key: str = "", *, client: httpx.Client | None = None
) -> EnrichmentResult | None:
    owned_client = client or get_client()
    params = {"key": api_key} if api_key else {}
    try:
        response = owned_client.get(f"{BASE_URL}/{external_id}", params=params)
        response.raise_for_status()
        info = response.json().get("volumeInfo", {})
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Google Books details fetch failed for %s: %s", external_id, exc)
        return None
    finally:
        if client is None:
            owned_client.close()

    if not info:
        return None

    published_date = info.get("publishedDate", "")
    year = int(published_date[:4]) if published_date[:4].isdigit() else None

    return EnrichmentResult(
        title=info.get("title"),
        authors=info.get("authors", []),
        genres=info.get("categories", []),
        summary=strip_html(info.get("description")),
        publisher=info.get("publisher"),
        published_year=year,
        language=info.get("language"),
        cover_url=_best_cover_url(info.get("imageLinks") or {}),
        external_ids={"google_books_id": external_id},
    )


def auto_match(title: str, api_key: str = "", *, client: httpx.Client | None = None) -> EnrichmentResult | None:
    candidates = search(title, api_key, client=client)
    index = best_match(title, [c.title for c in candidates])
    if index is None:
        return None
    return fetch_details(candidates[index].external_id, api_key, client=client)
