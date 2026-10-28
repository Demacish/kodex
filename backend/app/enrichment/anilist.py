"""AniList provider — used for the MANGA library type. Free GraphQL API,
no key required, but rate-limited (see AniList's API docs); a production
deployment enriching a large library in one go should add a small delay
between calls if it starts seeing 429s — not implemented here to keep this
first version simple.
"""

from __future__ import annotations

import logging

import httpx

from app.enrichment.base import Candidate, EnrichmentResult
from app.enrichment.http import get_client
from app.enrichment.text import best_match, strip_html

logger = logging.getLogger(__name__)

API_URL = "https://graphql.anilist.co"

_SEARCH_QUERY = """
query ($search: String) {
  Page(perPage: 10) {
    media(search: $search, type: MANGA) {
      id
      title { romaji english }
      startDate { year }
      coverImage { medium }
      staff(perPage: 1, sort: RELEVANCE) { edges { node { name { full } } } }
    }
  }
}
"""

_DETAILS_QUERY = """
query ($id: Int) {
  Media(id: $id, type: MANGA) {
    id
    title { romaji english }
    description(asHtml: false)
    genres
    startDate { year }
    coverImage { large }
    staff(perPage: 5) { edges { role node { name { full } } } }
  }
}
"""


def _display_title(title: dict) -> str:
    return title.get("english") or title.get("romaji") or "(namnlös)"


def search(query: str, *, client: httpx.Client | None = None) -> list[Candidate]:
    owned_client = client or get_client()
    try:
        response = owned_client.post(API_URL, json={"query": _SEARCH_QUERY, "variables": {"search": query}})
        response.raise_for_status()
        media_list = response.json().get("data", {}).get("Page", {}).get("media", [])
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("AniList search failed for %r: %s", query, exc)
        return []
    finally:
        if client is None:
            owned_client.close()

    candidates = []
    for media in media_list:
        staff_edges = media.get("staff", {}).get("edges", [])
        author = staff_edges[0]["node"]["name"]["full"] if staff_edges else None
        candidates.append(
            Candidate(
                external_id=str(media["id"]),
                title=_display_title(media.get("title", {})),
                year=(media.get("startDate") or {}).get("year"),
                thumbnail_url=(media.get("coverImage") or {}).get("medium"),
                subtitle=author,
            )
        )
    return candidates


def fetch_details(external_id: str, *, client: httpx.Client | None = None) -> EnrichmentResult | None:
    owned_client = client or get_client()
    try:
        response = owned_client.post(API_URL, json={"query": _DETAILS_QUERY, "variables": {"id": int(external_id)}})
        response.raise_for_status()
        media = response.json().get("data", {}).get("Media")
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("AniList details fetch failed for id %s: %s", external_id, exc)
        return None
    finally:
        if client is None:
            owned_client.close()

    if media is None:
        return None

    authors = [
        edge["node"]["name"]["full"]
        for edge in media.get("staff", {}).get("edges", [])
        if edge.get("role", "").lower() in ("story", "story & art", "art")
    ]

    return EnrichmentResult(
        title=_display_title(media.get("title", {})),
        authors=authors,
        genres=media.get("genres", []),
        summary=strip_html(media.get("description")),
        published_year=(media.get("startDate") or {}).get("year"),
        cover_url=(media.get("coverImage") or {}).get("large"),
        external_ids={"anilist_id": int(external_id)},
    )


_RELEASE_COUNT_QUERY = """
query ($id: Int) {
  Media(id: $id, type: MANGA) {
    volumes
    chapters
    status
  }
}
"""


def fetch_release_count(external_id: str, *, client: httpx.Client | None = None) -> int | None:
    """Published volume count for a manga, used by the weekly
    followed-series release check (see app/enrichment/release_check.py) —
    compared against how many volumes the library actually has.

    Important limitation, not a bug: AniList only reliably fills in
    `volumes` once a series is marked FINISHED. For a RELEASING (still
    ongoing) series — the normal case for something worth following — it's
    very often null, meaning this check simply can't tell yet for most
    currently-running manga. Falls back to `chapters` when `volumes` is
    null, since some entries populate one but not the other, but that's
    frequently null too for the same reason. Returns None (not 0) when
    neither is available, which the caller treats as "still can't tell"
    rather than "nothing published yet".
    """
    owned_client = client or get_client()
    try:
        response = owned_client.post(
            API_URL, json={"query": _RELEASE_COUNT_QUERY, "variables": {"id": int(external_id)}}
        )
        response.raise_for_status()
        media = response.json().get("data", {}).get("Media")
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("AniList release-count fetch failed for id %s: %s", external_id, exc)
        return None
    finally:
        if client is None:
            owned_client.close()

    if media is None:
        return None
    return media.get("volumes") or media.get("chapters")


def auto_match(series_title: str, *, client: httpx.Client | None = None) -> EnrichmentResult | None:
    candidates = search(series_title, client=client)
    index = best_match(series_title, [c.title for c in candidates])
    if index is None:
        return None
    return fetch_details(candidates[index].external_id, client=client)
