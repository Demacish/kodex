"""Metron (metron.cloud) — used ONLY for story arc discovery layered on
top of a Comic Vine match ("Metron-integration med Comic Vine arc som
fallback", requested 2026-09-11). Comic Vine remains the provider for
everything else a book needs (title, cover, summary, series/volume
grouping) — Metron is queried purely to find which story arc(s) an
already-Comic-Vine-matched issue belongs to, since Comic Vine's own
story_arc_credits field is sparse/rarely populated even for genuine
crossover issues (repeatedly confirmed against this library — see
engine.py's own notes), while Metron treats story arcs as a first-class,
actively-curated field. When Metron has nothing for an issue (not
configured, issue not cross-referenced yet, or genuinely no arc), the
caller falls back to whatever Comic Vine's own sparse credits already
produced — see engine.py's auto_enrich_book/apply_manual_match.

Cross-referenced via Comic Vine's own issue id (Metron calls this field
`cv_id`) — no fuzzy title/series matching needed between the two
providers, since the Comic Vine issue id is already known from the
primary match.

Authenticates with HTTP Basic Auth against a real Metron account
(settings.metron_username/metron_password) — Metron also supports a
revocable per-app API token as an alternative, but Basic Auth against the
account directly is what was requested 2026-09-11. Callers should skip
this provider entirely when either is unset, same "optional, degrades
gracefully" pattern as comicvine_api_key.

API shape (base URL, auth, rate limits, field names) confirmed against
Metron's own published docs and the official mokkari Python client's
schema definitions 2026-09-11 — NOT yet exercised against the live API
(this environment had no credentials to test with until the account
details were provided), so some field-name assumptions below may need a
small correction once actually run for real. Fails soft (logs + returns
[] / None) exactly like every other provider call in this app, so a
wrong assumption would show up as "Metron found nothing" rather than a
crash.
"""

from __future__ import annotations

import logging

import httpx

from app.enrichment.http import get_client
from app.enrichment.ratelimit import metron_limiter
from app.enrichment.story_arc_roster import ArcRosterItem

logger = logging.getLogger(__name__)

BASE_URL = "https://metron.cloud/api"


def _auth(username: str, password: str) -> httpx.BasicAuth:
    return httpx.BasicAuth(username, password)


def fetch_arcs_for_comicvine_issue(
    comicvine_issue_id: int, username: str, password: str, *, client: httpx.Client | None = None
) -> list[tuple[int, str]]:
    """The arc(s) a specific issue belongs to, per Metron — looked up by
    Comic Vine issue id (`cv_id`), the only id engine.py has at this
    point (right after a Comic Vine match). Two calls: the list endpoint
    (filtered by cv_id) only returns Metron's lightweight BaseIssue shape
    — no `arcs` field, confirmed against mokkari's schema — so the
    matched issue's own Metron id has to be re-fetched via the detail
    endpoint to get its real arc list. Returns [] for "no arcs" AND for
    any failure alike — the caller treats both as "nothing to override
    Comic Vine's own (possibly also empty) data with".
    """
    owned_client = client or get_client()
    auth = _auth(username, password)
    try:
        metron_limiter.acquire()
        response = owned_client.get(f"{BASE_URL}/issue/", params={"cv_id": comicvine_issue_id}, auth=auth)
        response.raise_for_status()
        results = response.json().get("results", [])
        if not results:
            return []
        metron_issue_id = results[0]["id"]

        metron_limiter.acquire()
        detail_response = owned_client.get(f"{BASE_URL}/issue/{metron_issue_id}/", auth=auth)
        detail_response.raise_for_status()
        arcs = detail_response.json().get("arcs") or []
        return [(arc["id"], arc["name"]) for arc in arcs if arc.get("id") and arc.get("name")]
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        logger.warning("Metron arc lookup failed for Comic Vine issue %s: %s", comicvine_issue_id, exc)
        return []
    finally:
        if client is None:
            owned_client.close()


def fetch_arc_roster(
    metron_arc_id: int, username: str, password: str, *, client: httpx.Client | None = None
) -> list[ArcRosterItem]:
    """An arc's full issue roster per Metron — the Metron equivalent of
    app/enrichment/story_arc_roster.py's Comic Vine version, feeding the
    SAME refresh_story_arc_task/StoryArc machinery (Uppdrag 7 Del D) for
    a StoryArc row linked to a Metron arc (metron_id) instead of a Comic
    Vine one (comicvine_id) — see StoryArc's own model docstring.

    Two-phase like the Comic Vine version, for the same reason: the
    roster endpoint (GET /arc/{id}/issue_list, DRF-paginated via `next`
    URLs) returns Metron's lightweight BaseIssue shape, which has
    `cover_date`/`image`/`number`/`issue` but NOT `cv_id` (confirmed
    against mokkari's schema — cv_id only exists on the full Issue detail
    shape) — so each roster issue needs its own detail fetch just to
    learn its Comic Vine id. Issues Metron can't cross-reference to Comic
    Vine (no cv_id even on detail) are skipped: this app's "which issues
    do we already own" check, and the "Skapa önskemål" missing-issue
    flow, are both keyed entirely on Comic Vine issue ids, so an
    unlinkable issue couldn't be matched or requested meaningfully
    either way. No batch/pipe-filter endpoint is documented for Metron
    (unlike Comic Vine's `filter=id:1|2|3`), so this is one call per
    roster issue — acceptable given Metron's much higher rate limit
    (20/min burst, 5000/day) and that this only ever runs for one arc at
    an admin's request, not across a whole library.
    """
    owned_client = client or get_client()
    auth = _auth(username, password)
    items: list[ArcRosterItem] = []
    try:
        url: str | None = f"{BASE_URL}/arc/{metron_arc_id}/issue_list"
        params: dict[str, str] | None = None
        roster: list[dict] = []
        while url:
            metron_limiter.acquire()
            response = owned_client.get(url, params=params, auth=auth)
            response.raise_for_status()
            payload = response.json()
            roster.extend(payload.get("results", []))
            url = payload.get("next")
            params = None  # `next` is already a complete URL with its own query string

        roster.sort(key=lambda issue: issue.get("cover_date") or "9999-99-99")

        for issue in roster:
            try:
                metron_limiter.acquire()
                detail_response = owned_client.get(f"{BASE_URL}/issue/{issue['id']}/", auth=auth)
                detail_response.raise_for_status()
                cv_id = detail_response.json().get("cv_id")
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                logger.warning("Metron issue detail fetch failed for issue %s: %s", issue.get("id"), exc)
                continue
            if not cv_id:
                continue

            series_name = (issue.get("series") or {}).get("name")
            number = issue.get("number")
            if series_name and number:
                display_name = f"{series_name} #{number}"
            elif issue.get("issue"):
                display_name = issue["issue"]
            else:
                display_name = series_name or f"Metron #{issue['id']}"

            items.append(
                ArcRosterItem(
                    comicvine_issue_id=int(cv_id),
                    display_name=display_name,
                    cover_url=issue.get("image"),
                    # Metron doesn't expose a confirmed public issue-detail
                    # page URL field on this shape — left null rather than
                    # guess a link pattern; StoryArcPanel.tsx already
                    # handles a null site_detail_url gracefully.
                    site_detail_url=None,
                    cover_date=issue.get("cover_date"),
                )
            )
        return items
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning("Metron arc roster fetch failed for arc %s: %s", metron_arc_id, exc)
        return items
    finally:
        if client is None:
            owned_client.close()
