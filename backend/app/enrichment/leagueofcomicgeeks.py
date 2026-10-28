"""League of Comic Geeks event/collection import — a fourth StoryArc
source alongside Comic Vine (story_arc_roster.py), Metron (metron.py) and
CBL-ReadingLists (cbl.py).

LoCG has no public API, and sits behind a Cloudflare JS/Turnstile
challenge that a plain httpx request can't pass — confirmed 2026-09-22,
a direct request comes back 403 with a "cf-mitigated: challenge" header,
the same class of block that already ruled out Metron as a reverse-lookup
source before FlareSolverr (a headless-browser proxy that solves the
challenge for us, run as a separate container) was set
up specifically to get past this one. Every request to leagueofcomicgeeks.com
goes through it via _fetch_html(); nothing here ever calls the site
directly.

Unlike CBL (which embeds a Comic Vine issue id on every entry directly),
an LoCG event page only gives its OWN numeric comic id — meaningless to
this app. Each entry's title text (already "Series Name #N", exactly the
shape Comic Vine's issue search wants — verified live) is resolved to a
Comic Vine issue id via a search, same principle as comicvine.py's own
volume-then-issue matching. An entry that can't be confidently resolved
(no exact issue-number match among the search results) is dropped rather
than guessed - see story_arc.py's own docstring on why every
StoryArcIssue needs a real comicvine_issue_id.
"""

from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings
from app.enrichment.http import get_client
from app.enrichment.ratelimit import comicvine_limiter
from app.enrichment.story_arc_roster import ArcRosterItem

logger = logging.getLogger(__name__)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")


def _normalize_series_name(text: str) -> str:
    """The series-name part of a "Series Name #N" title (or a bare volume
    name, which has no "#N" to strip and passes through unchanged),
    lowercased and stripped to bare alphanumerics for exact comparison —
    see _resolve_comicvine_issue_id for why this needs to be exact, not
    fuzzy."""
    series_part = _ISSUE_NUMBER_RE.split(text, maxsplit=1)[0]
    return _NON_ALNUM_RE.sub("", series_part.lower())


_EVENT_URL_RE = re.compile(r"leagueofcomicgeeks\.com/comics/event/(\d+)")
_ISSUE_NUMBER_RE = re.compile(r"#(\d+)")

# FlareSolverr's own headless-browser round trip (launch a page, wait for
# the Cloudflare challenge to clear, read the DOM) routinely takes 10-30s
# - far past enrichment_http_timeout_seconds (tuned for plain API calls),
# so this gets its own generous timeout instead of the shared get_client().
_FLARESOLVERR_TIMEOUT_SECONDS = 70.0


class LeagueOfComicGeeksError(Exception):
    """Fel vid hämtning/parsning av en League of Comic Geeks-sida, eller
    om FLARESOLVERR_URL inte är konfigurerat/nåbart."""


def parse_event_id(url_or_id: str) -> int | None:
    """Accepts either a full event URL (any slug — only the numeric id
    after /event/ is ever used) or a bare id typed directly."""
    text = url_or_id.strip()
    if text.isdigit():
        return int(text)
    match = _EVENT_URL_RE.search(text)
    return int(match.group(1)) if match else None


def _fetch_html(url: str) -> str:
    settings = get_settings()
    if not settings.flaresolverr_url:
        raise LeagueOfComicGeeksError("FLARESOLVERR_URL är inte konfigurerat.")
    try:
        response = httpx.post(
            f"{settings.flaresolverr_url.rstrip('/')}/v1",
            json={"cmd": "request.get", "url": url, "maxTimeout": 60000},
            timeout=_FLARESOLVERR_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise LeagueOfComicGeeksError(f"Kunde inte nå FlareSolverr: {exc}") from exc
    except ValueError as exc:
        raise LeagueOfComicGeeksError(f"Ogiltigt svar från FlareSolverr: {exc}") from exc

    if data.get("status") != "ok":
        raise LeagueOfComicGeeksError(f"FlareSolverr kunde inte hämta sidan: {data.get('message')}")
    solution = data.get("solution") or {}
    if solution.get("status") != 200:
        raise LeagueOfComicGeeksError(f"League of Comic Geeks svarade {solution.get('status')} via FlareSolverr.")
    return solution.get("response") or ""


def fetch_event_name(event_id: int) -> str | None:
    """Best-effort title for the admin's link-confirmation step - the
    <h1> is the same on every valid event page regardless of the URL's
    (cosmetic, ignored) slug."""
    html = _fetch_html(f"https://leagueofcomicgeeks.com/comics/event/{event_id}/-")
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1")
    return h1.get_text(strip=True) if h1 else None


def _parse_entries(html: str) -> list[tuple[int, str, str | None, str | None]]:
    """Returns (rank, title, cover_url, locg_comic_id) for every entry
    that's part of the event's actual reading order.

    Scoped per <li class="issue"> element (not a whole-document regex -
    tried that first, got a real title/id mismatch from a naive DOTALL
    span jumping into a neighbouring entry, see this module's commit
    message) so a malformed/missing field on one entry can never bleed
    into another's. Only entries with a rank are kept - LoCG lists every
    variant cover as its own <li> right after the entry it belongs to,
    with no rank of its own; without this filter a 20-issue event turns
    into ~130 near-duplicate rows, mostly cover variants of the same
    issue (confirmed against the "Queen in Black" event, 2026-09-22).
    """
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for li in soup.select("li.issue[data-comic]"):
        rank_el = li.select_one(".rank")
        if rank_el is None or not rank_el.get_text(strip=True).isdigit():
            continue
        title_el = li.select_one(".title[data-sorting]")
        title = title_el.get("data-sorting") if title_el else None
        if not title:
            continue
        img = li.select_one("img.lazy[data-src]")
        cover_url = img.get("data-src") if img else None
        entries.append((int(rank_el.get_text(strip=True)), title, cover_url, li.get("data-comic")))
    entries.sort(key=lambda e: e[0])
    return entries


def _resolve_comicvine_issue_id(title: str, api_key: str, *, client: httpx.Client) -> int | None:
    """title is LoCG's "Series Name #N" display title - already exactly
    the shape Comic Vine's issue search wants (verified live 2026-09-22:
    searching that literal string put the correct issue first every
    time). Still cross-checked against the issue number and, when
    several results share it, the closest volume-name match - never just
    trusts result[0]."""
    number_match = _ISSUE_NUMBER_RE.search(title)
    wanted_number = number_match.group(1) if number_match else None

    try:
        comicvine_limiter.acquire()
        response = client.get(
            "https://comicvine.gamespot.com/api/search/",
            params={
                "api_key": api_key,
                "format": "json",
                "resources": "issue",
                "query": title,
                "limit": 10,
                "field_list": "id,issue_number,volume",
            },
        )
        response.raise_for_status()
        results = response.json().get("results", [])
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Comic Vine-sökning misslyckades för LoCG-post %r: %s", title, exc)
        return None

    if wanted_number is not None:
        results = [r for r in results if str(r.get("issue_number")) == wanted_number]
    if not results:
        return None

    # Deliberately NOT text.best_match(): its fuzzy fallback tier scores
    # plain character overlap, and two different comics sharing a long
    # franchise-name prefix (e.g. "Queen in Black" vs "Queen in Black:
    # Venom Unchained") clear its 0.5 threshold easily on prefix overlap
    # alone - confirmed live 2026-09-22, it silently matched exactly that
    # pair. A wrong permanent match is worse than a dropped one here, so
    # this only accepts an EXACT normalized series-name match, never a
    # fuzzy one - Comic Vine's own search already did the fuzzy legwork
    # server-side; this just has to pick the right entry among what it
    # returned, not fuzzy-match a second time.
    wanted_series = _normalize_series_name(title)
    exact = [r for r in results if _normalize_series_name((r.get("volume") or {}).get("name") or "") == wanted_series]
    return exact[0]["id"] if exact else None


def fetch_event_roster(event_id: int) -> list[ArcRosterItem]:
    settings = get_settings()
    if not settings.comicvine_api_key:
        raise LeagueOfComicGeeksError("COMICVINE_API_KEY är inte konfigurerad - krävs för att slå upp LoCG-poster.")

    html = _fetch_html(f"https://leagueofcomicgeeks.com/comics/event/{event_id}/-")
    entries = _parse_entries(html)
    if not entries:
        raise LeagueOfComicGeeksError(
            "Hittade inga nummer på sidan - kontrollera länken, eller att LoCG inte ändrat sidstrukturen."
        )

    items: list[ArcRosterItem] = []
    with get_client() as client:
        for _rank, title, cover_url, comic_id in entries:
            issue_id = _resolve_comicvine_issue_id(title, settings.comicvine_api_key, client=client)
            if issue_id is None:
                logger.info("Ingen Comic Vine-träff för LoCG-post %r (LoCG-id %s) - hoppar över.", title, comic_id)
                continue
            items.append(
                ArcRosterItem(
                    comicvine_issue_id=issue_id,
                    display_name=title,
                    cover_url=cover_url,
                    site_detail_url=f"https://leagueofcomicgeeks.com/comic/{comic_id}" if comic_id else None,
                    cover_date=None,
                )
            )
    return items
