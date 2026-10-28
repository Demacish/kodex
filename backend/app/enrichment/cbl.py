"""CBL-ReadingLists (github.com/DieselTech/CBL-ReadingLists) — a
community-curated, static collection of named reading lists (crossover
events, creator runs, character reading orders, ...) in the CBL XML
format several comic readers already consume (Kavita, Komga, ComicRack,
Mylar, ...). Used here as a THIRD source for Uppdrag 7 Del D's story-arc
rosters, alongside Comic Vine (story_arc_roster.py) and Metron
(metron.py) — added 2026-09-11 after Metron turned out to be unreachable
from this server (its Anubis bot-protection blocking outbound
connections), and because every CBL entry already carries the Comic Vine
issue id directly:

    <Book Series="Batman" Number="484" Volume="1940" Year="1992">
      <Database Name="cv" Series="796" Issue="36110" />
    </Book>

— needing zero cross-provider matching, unlike Metron.

Structurally different from the other two sources: Comic Vine/Metron
answer "which arc(s) does this ALREADY-OWNED issue belong to" (a reverse
lookup, run automatically during enrichment — see engine.py's
_resolve_story_arcs); CBL only answers "give me this NAMED list's full
roster" — there's no per-issue reverse lookup at all, so CBL never
participates in that automatic path. It's purely a browse-and-link admin
flow instead (search by name, pick one, link it to a collection) — see
app/api/routes/cbl.py.

No API key, no auth, no meaningful rate limit: just static files served
over plain HTTPS from GitHub (raw.githubusercontent.com for file
content; api.github.com's Git Trees API — 60 unauthenticated
requests/hour — for the one-time file listing, cached below).
"""

from __future__ import annotations

import logging
import re
import threading
import time
import xml.etree.ElementTree as ET

import httpx

from app.enrichment.http import get_client
from app.enrichment.story_arc_roster import ArcRosterItem

logger = logging.getLogger(__name__)

REPO = "DieselTech/CBL-ReadingLists"
TREE_URL = f"https://api.github.com/repos/{REPO}/git/trees/main?recursive=1"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/main"

# The Trees API listing doesn't change fast enough to need fetching more
# often than this, and it's the one call here actually subject to a
# meaningful rate limit (60/hour unauthenticated) — a search box firing
# it on every keystroke would burn through that in seconds otherwise.
_TREE_TTL_SECONDS = 3600
_tree_lock = threading.Lock()
_tree_cache: list[str] | None = None
_tree_cached_at: float = 0.0


# Repo filenames are consistently "[Publisher] [Year range] Real Title
# (SOURCE-TAG)" — e.g. "[DC Comics] [1992-1995] Batman - Knightfall" or
# "[DC Comics] Knightfall Saga (WEB-CBRO)" — the bracket/paren noise
# isn't part of the actual event name, just filename metadata, but ended
# up leading (or trailing) the title everywhere it's shown. Reported
# 2026-09-11 as "[DC Comics] and the year end up first, or entirely in
# the small text". Stripped once here so both the search results AND
# whatever gets saved as the Collection/StoryArc name are already clean.
_LEADING_BRACKETS_RE = re.compile(r"^\s*\[[^\]]*\]\s*")
_TRAILING_PARENS_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _clean_name(raw: str) -> str:
    name = raw
    while True:
        stripped = _LEADING_BRACKETS_RE.sub("", name)
        if stripped == name:
            break
        name = stripped
    name = _TRAILING_PARENS_RE.sub("", name)
    name = name.strip(" -")
    return name or raw


class CblListSummary:
    __slots__ = ("path", "name", "publisher")

    def __init__(self, path: str, name: str, publisher: str) -> None:
        self.path = path
        self.name = name
        self.publisher = publisher


def _load_tree(client: httpx.Client) -> list[str]:
    global _tree_cache, _tree_cached_at
    with _tree_lock:
        if _tree_cache is not None and time.monotonic() - _tree_cached_at < _TREE_TTL_SECONDS:
            return _tree_cache
        response = client.get(TREE_URL, headers={"Accept": "application/vnd.github+json"})
        response.raise_for_status()
        paths = [entry["path"] for entry in response.json().get("tree", []) if entry.get("path", "").endswith(".cbl")]
        _tree_cache = paths
        _tree_cached_at = time.monotonic()
        return paths


def search_reading_lists(query: str, *, client: httpx.Client | None = None, limit: int = 25) -> list[CblListSummary]:
    """Case-insensitive, token-based match — loosened 2026-09-11 (was a
    plain substring match against the filename only, which meant word
    order mattered and the publisher couldn't be searched at all).

    Ranked in three tiers, best first, so the loosened matching doesn't
    come at the cost of precision for a query that would've worked under
    the old strict rule:
      0. The whole query is a substring of the filename (old behavior).
      1. Every word in the query appears somewhere in the filename, in
         any order (so "Knightfall Batman" now finds "Batman -
         Knightfall").
      2. Every word appears somewhere across filename + publisher folder
         combined (so "DC Knightfall" finds it via the publisher, or a
         query can mix a publisher name with part of the title).
    Ties within a tier keep the repo's own tree order. All matching is
    still exact-substring-per-word — no fuzzy/typo tolerance, that would
    need a real matching library for marginal benefit at this list size.
    """
    owned_client = client or get_client()
    try:
        paths = _load_tree(owned_client)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("CBL tree fetch failed: %s", exc)
        return []
    finally:
        if client is None:
            owned_client.close()

    needle = query.strip().lower()
    tokens = needle.split()
    if not tokens:
        return []

    scored: list[tuple[int, str, str, str]] = []  # (tier, path, raw_name, publisher)
    for path in paths:
        filename = path.rsplit("/", 1)[-1]
        raw_name = filename[:-4] if filename.endswith(".cbl") else filename
        publisher = path.split("/", 1)[0]
        name_haystack = raw_name.lower()

        if needle in name_haystack:
            tier = 0
        elif all(token in name_haystack for token in tokens):
            tier = 1
        elif all(token in f"{publisher} {raw_name}".lower() for token in tokens):
            tier = 2
        else:
            continue
        scored.append((tier, path, raw_name, publisher))

    scored.sort(key=lambda item: item[0])
    return [
        CblListSummary(path=path, name=_clean_name(raw_name), publisher=publisher)
        for _tier, path, raw_name, publisher in scored[:limit]
    ]


def fetch_reading_list(path: str, *, client: httpx.Client | None = None) -> list[ArcRosterItem]:
    """Downloads and parses one .cbl file's Book entries, in file order
    (trusted as reading order — the same assumption every CBL-consuming
    reader listed in the project's own README makes; there's no
    cover-date equivalent in this format to sort by instead). Issues
    with no <Database Name="cv"> Comic Vine reference are skipped, same
    reasoning as metron.py's cv_id-less issues: unlinkable to an owned
    book either way, and not worth a placeholder with nothing to show.
    """
    owned_client = client or get_client()
    try:
        response = owned_client.get(f"{RAW_BASE}/{path}")
        response.raise_for_status()
        root = ET.fromstring(response.text)
    except (httpx.HTTPError, ET.ParseError) as exc:
        logger.warning("CBL reading list fetch/parse failed for %s: %s", path, exc)
        return []
    finally:
        if client is None:
            owned_client.close()

    items: list[ArcRosterItem] = []
    for book in root.findall(".//Book"):
        cv_issue_id = None
        for database in book.findall("Database"):
            if database.get("Name") == "cv" and database.get("Issue"):
                cv_issue_id = database.get("Issue")
                break
        if not cv_issue_id:
            continue

        series = book.get("Series") or ""
        number = book.get("Number")
        display_name = f"{series} #{number}" if series and number else series or f"CBL-nummer {cv_issue_id}"

        items.append(
            ArcRosterItem(
                comicvine_issue_id=int(cv_issue_id),
                display_name=display_name,
                cover_url=None,
                site_detail_url=None,
                cover_date=None,
            )
        )
    return items
