"""Hand-written provider responses in the shape of the real APIs, with
invented titles and ids (recorded responses are never committed, see
docs/testing.md). ``record()`` builds one ReplayTransport entry."""

from __future__ import annotations

from typing import Any

CV = "https://comicvine.gamespot.com/api/"
METRON = "https://metron.cloud/api/"
MANGADEX = "https://api.mangadex.org/"
ANILIST = "https://graphql.anilist.co/"
MANGAUPDATES = "https://api.mangaupdates.com/v1/"
OPENLIBRARY = "https://openlibrary.org/"
GOOGLE = "https://www.googleapis.com/books/v1/"
RUN_FIELDS = "id,name,start_year,publisher,count_of_issues,aliases,image,site_detail_url"
ISSUE_FIELDS = "id,issue_number,cover_date,name,image,volume"


def record(method: str, url: str, params: dict[str, Any] | None = None, body: Any = None, *, status: int = 200,
           response: Any = None, headers: dict[str, str] | None = None) -> dict[str, Any]:  # fmt: skip
    return {
        "request": {"method": method, "url": url, "params": params or {}, "body": body},
        "response": {"status": status, "headers": headers or {}, "body": response},
    }


def cv_envelope(results: Any, total: int | None = None, status_code: int = 1, error: str = "OK") -> dict[str, Any]:
    count = len(results) if isinstance(results, list) else 1
    return {
        "error": error, "limit": 100, "offset": 0, "number_of_page_results": count,
        "number_of_total_results": total if total is not None else count, "status_code": status_code,
        "results": results, "version": "1.0",
    }  # fmt: skip


def cv_volume(
    volume_id: int, name: str, start_year: int, publisher: str | None, count: int, aliases: str | None = None
) -> dict[str, Any]:
    return {
        "aliases": aliases, "count_of_issues": count, "id": volume_id, "name": name, "start_year": str(start_year),
        "publisher": {"api_detail_url": "x", "id": 1, "name": publisher} if publisher else None,
        "image": {"original_url": f"https://cv.example/covers/{volume_id}.jpg"},
        "site_detail_url": f"https://comicvine.gamespot.com/x/4050-{volume_id}/",
    }  # fmt: skip


def cv_issue(issue_id: int, volume_id: int, number: str, cover_date: str, name: str | None = None) -> dict[str, Any]:
    return {
        "cover_date": cover_date, "id": issue_id, "issue_number": number, "name": name,
        "image": {"original_url": f"https://cv.example/issues/{issue_id}.jpg"},
        "volume": {"api_detail_url": "x", "id": volume_id, "name": "x", "site_detail_url": "x"},
    }  # fmt: skip


def cv_search(query: str, ids: list[int]) -> dict[str, Any]:
    return record(
        "GET", CV + "search/",
        {"format": "json", "resources": "volume", "query": query, "field_list": "id", "limit": "100"},
        response=cv_envelope([{"id": i, "resource_type": "volume"} for i in ids]),
    )  # fmt: skip


def cv_volumes(volumes: list[dict[str, Any]]) -> dict[str, Any]:
    ids = "|".join(str(v["id"]) for v in volumes)
    return record(
        "GET", CV + "volumes/", {"format": "json", "filter": f"id:{ids}", "field_list": RUN_FIELDS, "limit": "100"},
        response=cv_envelope(volumes),
    )  # fmt: skip


def cv_issues(
    volume_id: int, issues: list[dict[str, Any]], *, offset: int = 0, total: int | None = None
) -> dict[str, Any]:
    return record(
        "GET", CV + "issues/",
        {"format": "json", "filter": f"volume:{volume_id}", "field_list": ISSUE_FIELDS, "limit": "100",
         "offset": str(offset), "sort": "id:asc"},
        response=cv_envelope(issues, total=total),
    )  # fmt: skip


def metron_series(series_id: int, name: str, year: int, *, volume: int = 1, count: int = 12, publisher: str = "Northwind Comics",
                  series_type: str = "Ongoing Series", cv_id: int | None = None, year_end: int | None = None) -> dict[str, Any]:  # fmt: skip
    return {
        "id": series_id, "series": f"{name} ({year})", "year_began": year, "year_end": year_end, "volume": volume,
        "issue_count": count, "publisher": {"id": 1, "name": publisher}, "series_type": {"id": 1, "name": series_type},
        "cv_id": cv_id, "gcd_id": None, "modified": "2026-01-01T00:00:00Z",
    }  # fmt: skip


def metron_issue(issue_id: int, series_id: int, number: str, cover_date: str, *, cover_hash: str = "c3a5f00f0f0fa5c3",
                 cv_id: int | None = None, pages: int | None = None) -> dict[str, Any]:  # fmt: skip
    return {
        "id": issue_id, "series": {"id": series_id, "name": "x", "volume": 1, "year_began": 2016}, "number": number,
        "issue": f"x #{number}", "cover_date": cover_date, "store_date": None, "image": f"https://metron.example/{issue_id}.jpg",
        "cover_hash": cover_hash, "cv_id": cv_id, "gcd_id": None, "page": pages, "modified": "2026-01-01T00:00:00Z",
    }  # fmt: skip


def metron_page(results: list[dict[str, Any]], *, has_next: bool = False) -> dict[str, Any]:
    return {"count": len(results), "next": "https://metron.cloud/api/next" if has_next else None, "previous": None,
            "results": results}  # fmt: skip


def mangadex_manga(manga_id: str, title: str, *, year: int | None = 2020, alt: list[dict[str, str]] | None = None,
                   links: dict[str, str] | None = None, language: str = "ja") -> dict[str, Any]:  # fmt: skip
    return {
        "id": manga_id, "type": "manga",
        "attributes": {
            "title": {"en": title}, "altTitles": alt or [], "description": {"en": "An invented story."},
            "isLocked": False, "links": links or {}, "originalLanguage": language, "lastVolume": "", "lastChapter": "",
            "publicationDemographic": "shounen", "status": "ongoing", "year": year, "contentRating": "safe", "tags": [],
        },
        "relationships": [{"id": "cover-1", "type": "cover_art", "attributes": {"fileName": "cover.jpg"}}],
    }  # fmt: skip
