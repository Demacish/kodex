"""Manga providers:

- MangaDex (https://api.mangadex.org): titles in every language, links to
  AniList, MAL, MangaUpdates, Kitsu and shops, and the volume/chapter
  aggregate (scanlation volumes, not official tankōbon). About 5 calls a
  second per IP; a descriptive User-Agent is required. Free for
  non-commercial use with credit to MangaDex and the scanlation groups.
- AniList (GraphQL): romaji/English/native titles, synonyms, the MAL id,
  format (MANGA, NOVEL, ONE_SHOT), country, status, total volumes and
  staff. 90 calls a minute nominally, currently 30.
- MangaUpdates (v1 API): the ``associated`` names, best for scanlation
  titles. No published limit, so one call a second.
"""

from __future__ import annotations

from typing import Any

from kodex.matching.providers.base import IssueRef, ProviderClient, RatePolicy, RunCandidate

_MANGADEX_LINKS = {
    "al": "anilist",
    "mal": "mal",
    "mu": "mangaupdates",
    "kt": "kitsu",
    "ap": "animeplanet",
    "nu": "novelupdates",
}


def _pick_title(titles: dict[str, str]) -> str:
    for language in ("en", "ja-ro", "ko-ro", "zh-ro", "ja", "ko", "zh"):
        if titles.get(language):
            return titles[language]
    return next(iter(titles.values()), "")


class MangaDex(ProviderClient):
    name = "mangadex"
    base_url = "https://api.mangadex.org/"
    default_policy = RatePolicy(min_interval=0.25)

    def search_runs(self, query: str, *, limit: int = 10) -> list[RunCandidate]:
        payload = self.get(
            "manga",
            {"title": query, "limit": str(limit), "includes[]": "cover_art", "order[relevance]": "desc"},
        )
        return [_mangadex_run(item) for item in payload.get("data") or []]

    def get_run(self, run_id: str) -> RunCandidate:
        payload = self.get(f"manga/{run_id}", {"includes[]": "cover_art"}, lookup=True)
        return _mangadex_run(payload["data"])

    def list_issues(self, run_id: str) -> list[IssueRef]:
        """The chapter list from the aggregate: one entry per chapter, with
        the (scanlation) volume it was published in as its name."""
        payload = self.get(f"manga/{run_id}/aggregate", {}, lookup=True)
        volumes = payload.get("volumes") or {}
        if isinstance(volumes, list):  # an empty aggregate is a list
            volumes = {}
        issues = []
        for volume in volumes.values():
            chapters = volume.get("chapters") or {}
            if isinstance(chapters, list):
                chapters = {}
            for chapter in chapters.values():
                issues.append(
                    IssueRef(
                        provider="mangadex",
                        id=str(chapter.get("id") or f"{run_id}:{chapter.get('chapter')}"),
                        run_id=run_id,
                        number=chapter.get("chapter"),
                        name=None if volume.get("volume") in (None, "none") else f"v{volume.get('volume')}",
                        volume=None if volume.get("volume") in (None, "none") else str(volume.get("volume")),
                    )
                )
        return issues


def _mangadex_run(item: dict[str, Any]) -> RunCandidate:
    attributes = item.get("attributes") or {}
    titles = attributes.get("title") or {}
    aliases = [value for alt in attributes.get("altTitles") or [] for value in alt.values()]
    links = {"mangadex": item["id"]}
    for key, value in (attributes.get("links") or {}).items():
        if key in _MANGADEX_LINKS and value:
            links[_MANGADEX_LINKS[key]] = str(value)
    mu = links.get("mangaupdates", "")
    if mu.isalnum() and not mu.isdigit():
        # MangaDex gives MangaUpdates' current ids in base 36 ("abc12"),
        # the API in decimal (17324966). All digits is a legacy id that
        # the API no longer knows.
        links["mangaupdates"] = str(int(mu, 36))
    cover = next((rel for rel in item.get("relationships") or [] if rel.get("type") == "cover_art"), None)
    file_name = ((cover or {}).get("attributes") or {}).get("fileName")
    return RunCandidate(
        provider="mangadex",
        id=item["id"],
        name=_pick_title(titles),
        start_year=attributes.get("year"),
        aliases=[*(t for t in titles.values() if t != _pick_title(titles)), *aliases],
        cover_url=f"https://uploads.mangadex.org/covers/{item['id']}/{file_name}" if file_name else None,
        format="manga",
        language=attributes.get("originalLanguage"),
        status=attributes.get("status"),
        summary=(attributes.get("description") or {}).get("en"),
        url=f"https://mangadex.org/title/{item['id']}",
        links=links,
    )


_ANILIST_QUERY = """
query ($search: String, $id: Int) {
  Page(perPage: 10) {
    media(search: $search, id: $id, type: MANGA) {
      id idMal format status countryOfOrigin volumes chapters
      title { romaji english native }
      synonyms
      startDate { year }
      endDate { year }
      coverImage { large }
      siteUrl
      staff(perPage: 4) { edges { role node { name { full } } } }
    }
  }
}
"""
_ANILIST_FORMATS = {"MANGA": "manga", "NOVEL": "novel", "ONE_SHOT": "one_shot"}


class AniList(ProviderClient):
    name = "anilist"
    base_url = "https://graphql.anilist.co/"
    default_policy = RatePolicy(min_interval=2.0)

    def _media(self, variables: dict[str, Any], *, lookup: bool) -> list[dict[str, Any]]:
        payload = self.post("", {"query": _ANILIST_QUERY, "variables": variables}, lookup=lookup)
        return ((payload.get("data") or {}).get("Page") or {}).get("media") or []

    def search_runs(self, query: str) -> list[RunCandidate]:
        return [_anilist_run(media) for media in self._media({"search": query}, lookup=False)]

    def get_run(self, run_id: str) -> RunCandidate:
        media = self._media({"id": int(run_id)}, lookup=True)
        if not media:
            from kodex.matching.providers.base import NotFound

            raise NotFound(f"anilist: {run_id}")
        return _anilist_run(media[0])


def _anilist_run(media: dict[str, Any]) -> RunCandidate:
    title = media.get("title") or {}
    name = title.get("english") or title.get("romaji") or title.get("native") or ""
    aliases = [t for t in (title.get("romaji"), title.get("english"), title.get("native")) if t and t != name]
    links = {"anilist": str(media["id"])}
    if media.get("idMal"):
        links["mal"] = str(media["idMal"])
    return RunCandidate(
        provider="anilist",
        id=str(media["id"]),
        name=name,
        start_year=(media.get("startDate") or {}).get("year"),
        end_year=(media.get("endDate") or {}).get("year"),
        issue_count=media.get("volumes"),
        aliases=aliases + list(media.get("synonyms") or []),
        cover_url=(media.get("coverImage") or {}).get("large"),
        format=_ANILIST_FORMATS.get(str(media.get("format")), str(media.get("format") or "").lower() or None),
        country=media.get("countryOfOrigin"),
        status=(media.get("status") or "").lower() or None,
        url=media.get("siteUrl"),
        links=links,
    )


class MangaUpdates(ProviderClient):
    name = "mangaupdates"
    base_url = "https://api.mangaupdates.com/v1/"
    default_policy = RatePolicy(min_interval=1.0)

    def search_runs(self, query: str) -> list[RunCandidate]:
        payload = self.post("series/search", {"search": query, "perpage": 10})
        return [_mangaupdates_run(hit.get("record") or {}) for hit in payload.get("results") or []]

    def get_run(self, run_id: str) -> RunCandidate:
        return _mangaupdates_run(self.get(f"series/{run_id}", lookup=True))


def _mangaupdates_run(record: dict[str, Any]) -> RunCandidate:
    series_id = str(record.get("series_id", ""))
    year = str(record.get("year") or "")
    kind = str(record.get("type") or "").lower()
    image = ((record.get("image") or {}).get("url") or {}).get("original")
    return RunCandidate(
        provider="mangaupdates",
        id=series_id,
        name=str(record.get("title") or ""),
        start_year=int(year) if year[:4].isdigit() else None,
        aliases=[a.get("title", "") for a in record.get("associated") or [] if a.get("title")],
        cover_url=image,
        format="novel" if "novel" in kind else "manga",
        status=record.get("status"),
        url=record.get("url"),
        links={"mangaupdates": series_id},
    )
