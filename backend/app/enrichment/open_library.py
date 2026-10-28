"""Open Library provider — used for the EBOOKS library type. Free API, no
key required. When a book has an ISBN (parsed from the EPUB's OPF
metadata, see scanning/parsers/epub_meta.py) that's used for a direct,
much more reliable lookup instead of a title search.
"""

from __future__ import annotations

import logging

import httpx

from app.enrichment.base import Candidate, EnrichmentResult
from app.enrichment.http import get_client
from app.enrichment.text import best_match, strip_html

logger = logging.getLogger(__name__)

BASE_URL = "https://openlibrary.org"
COVERS_URL = "https://covers.openlibrary.org/b"


def _cover_url(cover_id: int | None) -> str | None:
    return f"{COVERS_URL}/id/{cover_id}-L.jpg" if cover_id else None


def search(query: str, *, client: httpx.Client | None = None) -> list[Candidate]:
    owned_client = client or get_client()
    try:
        response = owned_client.get(f"{BASE_URL}/search.json", params={"q": query, "limit": 10})
        response.raise_for_status()
        docs = response.json().get("docs", [])
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Open Library search failed for %r: %s", query, exc)
        return []
    finally:
        if client is None:
            owned_client.close()

    candidates = []
    for doc in docs:
        authors = doc.get("author_name") or []
        candidates.append(
            Candidate(
                external_id=doc["key"],  # e.g. "/works/OL123W"
                title=doc.get("title") or "(namnlös)",
                year=doc.get("first_publish_year"),
                thumbnail_url=_cover_url(doc.get("cover_i")),
                subtitle=", ".join(authors[:2]) or None,
            )
        )
    return candidates


def fetch_details(external_id: str, *, client: httpx.Client | None = None) -> EnrichmentResult | None:
    """external_id is a work key like "/works/OL123W" (from search(), or
    typed in directly for a manual match).
    """
    owned_client = client or get_client()
    try:
        response = owned_client.get(f"{BASE_URL}{external_id}.json")
        response.raise_for_status()
        work = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Open Library work fetch failed for %s: %s", external_id, exc)
        return None
    finally:
        if client is None:
            owned_client.close()

    description = work.get("description")
    if isinstance(description, dict):
        description = description.get("value")

    covers = work.get("covers") or []
    subjects = work.get("subjects") or []

    return EnrichmentResult(
        title=work.get("title"),
        genres=[s for s in subjects if isinstance(s, str)][:10],
        summary=strip_html(description),
        cover_url=_cover_url(covers[0]) if covers else None,
        external_ids={"open_library_key": external_id},
    )


def fetch_by_isbn(isbn: str, *, client: httpx.Client | None = None) -> EnrichmentResult | None:
    """A direct ISBN lookup, far more reliable than a title search when we
    have one — the combined `jscmd=data` endpoint conveniently includes
    authors, publisher and cover in a single call.
    """
    owned_client = client or get_client()
    try:
        response = owned_client.get(
            f"{BASE_URL}/api/books",
            params={"bibkeys": f"ISBN:{isbn}", "format": "json", "jscmd": "data"},
        )
        response.raise_for_status()
        data = response.json().get(f"ISBN:{isbn}")
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Open Library ISBN lookup failed for %s: %s", isbn, exc)
        return None
    finally:
        if client is None:
            owned_client.close()

    if not data:
        return None

    publishers = data.get("publishers") or []
    subjects = data.get("subjects") or []
    cover = (data.get("cover") or {}).get("large")

    return EnrichmentResult(
        title=data.get("title"),
        authors=[a["name"] for a in data.get("authors", [])],
        genres=[s.get("name") for s in subjects if isinstance(s, dict) and s.get("name")][:10],
        publisher=publishers[0]["name"] if publishers else None,
        published_year=int(data["publish_date"][-4:]) if data.get("publish_date", "")[-4:].isdigit() else None,
        cover_url=cover,
        external_ids={"open_library_isbn": isbn},
    )


def auto_match(title: str, isbn: str | None = None, *, client: httpx.Client | None = None) -> EnrichmentResult | None:
    if isbn:
        result = fetch_by_isbn(isbn, client=client)
        if result is not None:
            return result
        logger.info("ISBN %s not found on Open Library, falling back to title search", isbn)

    candidates = search(title, client=client)
    index = best_match(title, [c.title for c in candidates])
    if index is None:
        return None
    return fetch_details(candidates[index].external_id, client=client)
