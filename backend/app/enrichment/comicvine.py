"""Comic Vine provider — used for the COMICS library type.

Comic Vine models a series as a "volume" and each issue separately. We
match on the volume (series) first, then try to find the specific issue by
number for a per-book summary/cover; if that fails we fall back to
volume-level data for every book in the series.

Requires a free API key (settings.comicvine_api_key) — see
https://comicvine.gamespot.com/api/. If no key is configured, callers
should skip this provider entirely (see engine.py).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.enrichment.base import Candidate, EnrichmentResult
from app.enrichment.http import get_client
from app.enrichment.ratelimit import comicvine_limiter
from app.enrichment.text import best_match, strip_html

logger = logging.getLogger(__name__)

BASE_URL = "https://comicvine.gamespot.com/api"


def search(query: str, api_key: str, *, client: httpx.Client | None = None) -> list[Candidate]:
    """Search for a series (volume). Returns up to 10 candidates, Comic
    Vine's own relevance-ranked order preserved.
    """
    owned_client = client or get_client()
    try:
        comicvine_limiter.acquire()
        response = owned_client.get(
            f"{BASE_URL}/search/",
            params={
                "api_key": api_key,
                "format": "json",
                "query": query,
                "resources": "volume",
                "limit": 10,
                "field_list": "id,name,start_year,publisher,image,count_of_issues",
            },
        )
        response.raise_for_status()
        results = response.json().get("results", [])
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Comic Vine search failed for %r: %s", query, exc)
        return []
    finally:
        if client is None:
            owned_client.close()

    candidates = []
    for volume in results:
        issue_count = volume.get("count_of_issues")
        candidates.append(
            Candidate(
                external_id=str(volume["id"]),
                title=volume.get("name") or "(namnlös)",
                year=volume.get("start_year"),
                thumbnail_url=(volume.get("image") or {}).get("thumb_url"),
                subtitle=(volume.get("publisher") or {}).get("name")
                or (f"{issue_count} nummer" if issue_count else None),
                issue_count=issue_count,
            )
        )
    return candidates


def _fetch_volume(volume_id: str, api_key: str, client: httpx.Client) -> dict | None:
    try:
        comicvine_limiter.acquire()
        response = client.get(
            f"{BASE_URL}/volume/4050-{volume_id}/",
            params={"api_key": api_key, "format": "json"},
        )
        response.raise_for_status()
        return response.json().get("results")
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Comic Vine volume fetch failed for %s: %s", volume_id, exc)
        return None


def _fetch_issue_by_number(volume_id: str, issue_number: float, api_key: str, client: httpx.Client) -> dict | None:
    # Comic Vine issue numbers are stored as strings; try both "3" and
    # "3.0"-style formatting since publishers are inconsistent.
    number_variants = {str(issue_number), str(int(issue_number)) if issue_number == int(issue_number) else None}
    for variant in filter(None, number_variants):
        try:
            comicvine_limiter.acquire()
            response = client.get(
                f"{BASE_URL}/issues/",
                params={
                    "api_key": api_key,
                    "format": "json",
                    "filter": f"volume:{volume_id},issue_number:{variant}",
                    "field_list": "id,name,issue_number,description,cover_date,image,story_arc_credits",
                },
            )
            response.raise_for_status()
            results = response.json().get("results", [])
            if results:
                return results[0]
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Comic Vine issue lookup failed for volume %s #%s: %s", volume_id, variant, exc)
    return None


def fetch_details(
    external_id: str, api_key: str, *, issue_number: float | None = None, client: httpx.Client | None = None
) -> EnrichmentResult | None:
    """Fetch full volume (+ issue, if issue_number given) details for a
    previously-found (or manually chosen) volume id.
    """
    owned_client = client or get_client()
    try:
        volume = _fetch_volume(external_id, api_key, owned_client)
        if volume is None:
            return None

        result = EnrichmentResult(
            title=volume.get("name"),
            series_title=volume.get("name"),
            publisher=(volume.get("publisher") or {}).get("name"),
            published_year=volume.get("start_year"),
            summary=strip_html(volume.get("description")),
            cover_url=(volume.get("image") or {}).get("medium_url"),
            external_ids={"comicvine_volume_id": int(external_id)},
        )

        if issue_number is not None:
            issue = _fetch_issue_by_number(external_id, issue_number, api_key, owned_client)
            if issue:
                if issue.get("name"):
                    result.title = issue["name"]
                if issue.get("description"):
                    result.summary = strip_html(issue["description"])
                if (issue.get("image") or {}).get("medium_url"):
                    result.cover_url = issue["image"]["medium_url"]
                if issue.get("cover_date"):
                    result.published_year = int(issue["cover_date"][:4])
                result.external_ids["comicvine_issue_id"] = issue["id"]
                arc_credits = [arc for arc in issue.get("story_arc_credits") or [] if arc.get("name")]
                result.story_arcs = [arc["name"] for arc in arc_credits]
                result.story_arc_ids = {arc["name"]: arc["id"] for arc in arc_credits if arc.get("id")}

        return result
    finally:
        if client is None:
            owned_client.close()


def list_issues(volume_id: str, api_key: str, *, client: httpx.Client | None = None) -> list[Candidate]:
    """Every issue of one volume, in reading order — the second step of
    manual matching (F): once a user has picked the right series/volume
    from search() above, this lets them pick the specific issue directly
    instead of relying on auto_enrich_book's book.number-based guess
    (see _fetch_issue_by_number), which fails outright for a book whose
    number couldn't be parsed at all, or double-matches two books that
    parsed to the same number (e.g. a single issue and a same-numbered
    collected edition — see Book.edition_type).
    """
    owned_client = client or get_client()
    try:
        comicvine_limiter.acquire()
        response = owned_client.get(
            f"{BASE_URL}/issues/",
            params={
                "api_key": api_key,
                "format": "json",
                "filter": f"volume:{volume_id}",
                "sort": "issue_number:asc",
                "limit": 100,
                "field_list": "id,name,issue_number,cover_date,image",
            },
        )
        response.raise_for_status()
        results = response.json().get("results", [])
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Comic Vine issue list failed for volume %s: %s", volume_id, exc)
        return []
    finally:
        if client is None:
            owned_client.close()

    candidates = []
    for issue in results:
        cover_date = issue.get("cover_date")
        number = issue.get("issue_number")
        candidates.append(
            Candidate(
                external_id=str(issue["id"]),
                title=issue.get("name") or (f"#{number}" if number else "(namnlös)"),
                year=int(cover_date[:4]) if cover_date else None,
                thumbnail_url=(issue.get("image") or {}).get("thumb_url"),
                subtitle=f"#{number}" if number else None,
            )
        )
    return candidates


@dataclass
class IssueRelease:
    """One volume's issue, as needed by B5's release calendar — a
    separate, purpose-built shape from Candidate (used for the manual-
    match search UI) since a calendar needs the raw store_date/
    issue_number Candidate doesn't carry, and has no use for a thumbnail.
    See list_issue_releases below and release_check.py's
    _sync_release_events.
    """

    external_id: str
    issue_number: str | None
    title: str | None
    # Comic Vine's raw date strings (e.g. "2025-06-15 00:00:00" or just a
    # date) — left unparsed here so this module stays free of a date-
    # parsing dependency; release_check.py parses them.
    store_date: str | None
    cover_date: str | None


def list_issue_releases(volume_id: str, api_key: str, *, client: httpx.Client | None = None) -> list[IssueRelease]:
    """Every issue of one volume with its store date — B5's data source
    for the release calendar/pull-list. Separate call from list_issues()
    above (rather than widening Candidate) since store_date is
    B5-specific and Comic Vine's field_list needs to actually ask for it.
    """
    owned_client = client or get_client()
    try:
        comicvine_limiter.acquire()
        response = owned_client.get(
            f"{BASE_URL}/issues/",
            params={
                "api_key": api_key,
                "format": "json",
                "filter": f"volume:{volume_id}",
                "sort": "issue_number:asc",
                "limit": 100,
                "field_list": "id,name,issue_number,store_date,cover_date",
            },
        )
        response.raise_for_status()
        results = response.json().get("results", [])
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Comic Vine issue release list failed for volume %s: %s", volume_id, exc)
        return []
    finally:
        if client is None:
            owned_client.close()

    return [
        IssueRelease(
            external_id=str(issue["id"]),
            issue_number=issue.get("issue_number"),
            title=issue.get("name"),
            store_date=issue.get("store_date"),
            cover_date=issue.get("cover_date"),
        )
        for issue in results
    ]


def fetch_issue_details(issue_id: str, api_key: str, *, client: httpx.Client | None = None) -> EnrichmentResult | None:
    """Full details for one issue the user picked directly from
    list_issues() above — the issue-level counterpart of fetch_details(),
    used when a manual match specifies an issue id rather than a volume
    id (see engine.py's apply_manual_match `is_issue` flag). Looks up the
    issue's own volume for series_title/comicvine_volume_id so
    _reparent_to_canonical_series still works exactly as it does for a
    volume-level match.
    """
    owned_client = client or get_client()
    try:
        comicvine_limiter.acquire()
        response = owned_client.get(
            f"{BASE_URL}/issue/4000-{issue_id}/",
            params={
                "api_key": api_key,
                "format": "json",
                "field_list": "id,name,description,cover_date,image,volume,story_arc_credits",
            },
        )
        response.raise_for_status()
        issue = response.json().get("results")
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Comic Vine issue fetch failed for %s: %s", issue_id, exc)
        return None
    finally:
        if client is None:
            owned_client.close()

    if issue is None:
        return None

    volume = issue.get("volume") or {}
    arc_credits = [arc for arc in issue.get("story_arc_credits") or [] if arc.get("name")]

    result = EnrichmentResult(
        title=issue.get("name") or volume.get("name"),
        series_title=volume.get("name"),
        summary=strip_html(issue.get("description")),
        cover_url=(issue.get("image") or {}).get("medium_url"),
        published_year=int(issue["cover_date"][:4]) if issue.get("cover_date") else None,
        story_arcs=[arc["name"] for arc in arc_credits],
        story_arc_ids={arc["name"]: arc["id"] for arc in arc_credits if arc.get("id")},
        external_ids={"comicvine_issue_id": int(issue_id)},
    )
    if volume.get("id") is not None:
        result.external_ids["comicvine_volume_id"] = volume["id"]
    return result


def fetch_issue_count(volume_id: str, api_key: str, *, client: httpx.Client | None = None) -> int | None:
    """Just the published issue count for a volume — lighter-weight than
    fetch_details() (one field instead of a full detail fetch), used by
    the weekly followed-series release check (see
    app/enrichment/release_check.py) rather than by normal enrichment.

    Treated as "how many issues exist" and compared against how many the
    library actually has. Assumes issue numbering is contiguous from 1,
    which holds for the vast majority of Comic Vine volumes but isn't
    guaranteed (annuals, renumbered runs) — a best-effort heuristic, not a
    promise that a flagged series is missing exactly that issue.
    """
    owned_client = client or get_client()
    try:
        comicvine_limiter.acquire()
        response = owned_client.get(
            f"{BASE_URL}/volume/4050-{volume_id}/",
            params={"api_key": api_key, "format": "json", "field_list": "count_of_issues"},
        )
        response.raise_for_status()
        result = response.json().get("results")
        return result.get("count_of_issues") if result else None
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Comic Vine issue-count fetch failed for volume %s: %s", volume_id, exc)
        return None
    finally:
        if client is None:
            owned_client.close()


def search_story_arc_description(name: str, api_key: str, *, client: httpx.Client | None = None) -> str | None:
    """Best-effort synopsis lookup for a story arc found some OTHER way
    (currently: CBL-ReadingLists — see cbl.py's link() route, which has a
    name but no description of its own, that format having none).

    Uses the dedicated /story_arcs/ list endpoint with filter=name:...,
    NOT the general /search/ endpoint — confirmed live 2026-09-11 that
    /search/?resources=story_arc is broken on Comic Vine's side (claims
    number_of_page_results=10 but always returns an empty results array,
    for any query); /story_arcs/?filter=name:... works correctly but
    does a CONTAINS match against Comic Vine's own arc name, not a fuzzy
    one — "Batman - Knightfall" (this app's cleaned CBL name) matches
    NOTHING against Comic Vine's own "\"Batman\" Knightfall", while the
    bare word "Knightfall" does. So: try the full name first, and if
    that comes back empty, retry with just the text after the last
    " - " (CBL names are consistently "Qualifier - Event", and the event
    half alone is usually enough to be a substring of Comic Vine's own
    name). Either way, best_match then picks the closest of whatever
    candidates came back, rather than trusting result order. Returns
    None on no match (either attempt) or any failure — this is
    decoration, not something worth failing a link() call over.
    """
    owned_client = client or get_client()

    def _query(filter_term: str) -> list[dict]:
        comicvine_limiter.acquire()
        response = owned_client.get(
            f"{BASE_URL}/story_arcs/",
            params={
                "api_key": api_key,
                "format": "json",
                "filter": f"name:{filter_term}",
                "field_list": "id,name,description",
                "limit": 10,
            },
        )
        response.raise_for_status()
        return response.json().get("results", [])

    try:
        results = _query(name)
        if not results and " - " in name:
            results = _query(name.rsplit(" - ", 1)[-1].strip())
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Comic Vine story arc search failed for %r: %s", name, exc)
        return None
    finally:
        if client is None:
            owned_client.close()

    index = best_match(name, [r.get("name") or "" for r in results])
    if index is None:
        return None
    return strip_html(results[index].get("description"))


def auto_match(
    series_title: str, issue_number: float | None, api_key: str, *, client: httpx.Client | None = None
) -> EnrichmentResult | None:
    """Convenience wrapper for the automatic enrichment engine: search, pick
    the best match, then fetch full details for it. Manual matching (the
    user picking from `search()` results themselves) calls fetch_details()
    directly with the chosen id instead.
    """
    candidates = search(series_title, api_key, client=client)
    weights = [c.issue_count or 0 for c in candidates]
    index = best_match(series_title, [c.title for c in candidates], weights=weights)
    if index is None:
        return None
    return fetch_details(candidates[index].external_id, api_key, issue_number=issue_number, client=client)
