"""Fetches a Comic Vine story arc's FULL issue roster — distinct from
comicvine.py's story_arc_credits handling, which only ever tells you
which arc(s) one already-owned issue belongs to. This is the reverse
direction: given an arc, what does Comic Vine say the complete reading
list is, so app/models/story_arc.py's StoryArcIssue rows can show a
"Saknas" placeholder for anything we don't own (Uppdrag 7 Del D).
"""

from __future__ import annotations

import logging

import httpx

from app.enrichment.http import get_client
from app.enrichment.ratelimit import comicvine_limiter

logger = logging.getLogger(__name__)

BASE_URL = "https://comicvine.gamespot.com/api"

# Comic Vine issue-detail filter URLs get long fast with a pipe-separated
# id list — chunking keeps well clear of any URL-length limit regardless
# of how big an arc's roster is.
_DETAIL_BATCH_SIZE = 40


class ArcRosterItem:
    __slots__ = ("comicvine_issue_id", "display_name", "cover_url", "site_detail_url", "cover_date")

    def __init__(
        self,
        comicvine_issue_id: int,
        display_name: str,
        cover_url: str | None,
        site_detail_url: str | None,
        cover_date: str | None,
    ) -> None:
        self.comicvine_issue_id = comicvine_issue_id
        self.display_name = display_name
        self.cover_url = cover_url
        self.site_detail_url = site_detail_url
        self.cover_date = cover_date


def fetch_arc_name(comicvine_arc_id: int, api_key: str, *, client: httpx.Client | None = None) -> str | None:
    """C15 — just the arc's own name, for POST /collections/story-arc-
    import (an admin typing in a bare Comic Vine story-arc id to start
    tracking an arc from scratch, before owning a single issue from it —
    see build_story_arc_collection in app/api/routes/collections.py). A
    separate, cheap call from fetch_arc_roster below rather than widening
    that function's return shape, since every *existing* caller of
    fetch_arc_roster already knows the arc's name (see StoryArc.name,
    always set before a roster refresh is ever triggered).
    """
    owned_client = client or get_client()
    try:
        comicvine_limiter.acquire()
        response = owned_client.get(
            f"{BASE_URL}/story_arc/4045-{comicvine_arc_id}/",
            params={"api_key": api_key, "format": "json", "field_list": "id,name"},
        )
        response.raise_for_status()
        arc = response.json().get("results")
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Comic Vine story arc name fetch failed for %s: %s", comicvine_arc_id, exc)
        return None
    finally:
        if client is None:
            owned_client.close()

    return (arc or {}).get("name")


def fetch_arc_roster(comicvine_arc_id: int, api_key: str, *, client: httpx.Client | None = None) -> list[ArcRosterItem]:
    """Returns every issue Comic Vine lists for this arc, ordered by cover
    date (oldest first — reading order). Comic Vine's own story_arc
    "issues" field gives no ordering or issue-level detail at all (just
    id/name/url refs), so this is a two-step fetch: the roster of ids,
    then a batched detail fetch (see _DETAIL_BATCH_SIZE) for cover_date/
    issue_number/volume/image to actually build something orderable and
    displayable. Returns [] on any failure — a story arc admins can't
    currently refresh isn't worth crashing the whole request over.
    """
    owned_client = client or get_client()
    try:
        try:
            comicvine_limiter.acquire()
            response = owned_client.get(
                f"{BASE_URL}/story_arc/4045-{comicvine_arc_id}/",
                params={"api_key": api_key, "format": "json", "field_list": "id,name,issues"},
            )
            response.raise_for_status()
            arc = response.json().get("results")
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Comic Vine story arc fetch failed for %s: %s", comicvine_arc_id, exc)
            return []

        if not arc:
            return []
        issue_refs = arc.get("issues") or []
        issue_ids = [ref["id"] for ref in issue_refs if ref.get("id")]
        if not issue_ids:
            return []

        details_by_id: dict[int, dict] = {}
        for start in range(0, len(issue_ids), _DETAIL_BATCH_SIZE):
            batch = issue_ids[start : start + _DETAIL_BATCH_SIZE]
            try:
                comicvine_limiter.acquire()
                response = owned_client.get(
                    f"{BASE_URL}/issues/",
                    params={
                        "api_key": api_key,
                        "format": "json",
                        "filter": f"id:{'|'.join(str(i) for i in batch)}",
                        "field_list": "id,name,issue_number,cover_date,image,volume,site_detail_url",
                        "limit": len(batch),
                    },
                )
                response.raise_for_status()
                for issue in response.json().get("results", []):
                    details_by_id[issue["id"]] = issue
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning(
                    "Comic Vine issue-detail batch fetch failed for arc %s (ids %s): %s", comicvine_arc_id, batch, exc
                )

        items = []
        for issue_id in issue_ids:
            issue = details_by_id.get(issue_id)
            if issue is None:
                # A ref Comic Vine listed on the arc but whose own detail
                # fetch failed/was missing — skip rather than show a
                # placeholder with no real information to display.
                continue
            volume_name = (issue.get("volume") or {}).get("name")
            issue_number = issue.get("issue_number")
            if volume_name and issue_number:
                display_name = f"{volume_name} #{issue_number}"
            elif issue.get("name"):
                display_name = issue["name"]
            else:
                display_name = volume_name or f"Nummer {issue_id}"

            items.append(
                ArcRosterItem(
                    comicvine_issue_id=issue_id,
                    display_name=display_name,
                    cover_url=(issue.get("image") or {}).get("medium_url"),
                    site_detail_url=issue.get("site_detail_url"),
                    cover_date=issue.get("cover_date"),
                )
            )

        items.sort(key=lambda item: item.cover_date or "9999-99-99")
        return items
    finally:
        if client is None:
            owned_client.close()
