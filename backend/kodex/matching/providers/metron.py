"""Metron (https://metron.cloud): series, issues with precomputed cover
hashes, and bridges to Comic Vine (``cv_id``) and the GCD (``gcd_id``) on
both series and issues. HTTP Basic auth; 20 calls a minute in bursts and
5 000 a day."""

from __future__ import annotations

from typing import Any

import httpx

from kodex.matching.providers.base import IssueRef, NotConfigured, ProviderClient, RatePolicy, RunCandidate

_SERIES_TYPES = {
    "trade paperback": "collected", "hard cover": "collected", "hardcover": "collected", "omnibus": "collected",
    "graphic novel": "collected", "one-shot": "one_shot", "annual series": "annual", "digital chapter": "chapter",
}  # fmt: skip


class Metron(ProviderClient):
    name = "metron"
    base_url = "https://metron.cloud/api/"
    default_policy = RatePolicy(min_interval=3.0, window=86400.0, window_limit=5000)

    def __init__(self, *, username: str, password: str, **kwargs: Any) -> None:
        if not username or not password:
            raise NotConfigured("metron: METRON_USERNAME/METRON_PASSWORD are not set")
        self.username = username
        self.password = password
        super().__init__(**kwargs)

    def http_auth(self) -> httpx.Auth | None:
        return httpx.BasicAuth(self.username, self.password)

    def _pages(self, path: str, params: dict[str, str], *, lookup: bool, max_pages: int = 20) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            payload = self.get(path, {**params, "page": str(page)}, lookup=lookup)
            results += payload.get("results") or []
            if not payload.get("next"):
                break
        return results

    def search_runs(self, query: str, *, year: int | None = None) -> list[RunCandidate]:
        params = {"name": query}
        if year is not None:
            params["year_began"] = str(year)
        return [_run_summary(item) for item in self._pages("series/", params, lookup=False, max_pages=3)]

    def get_run(self, run_id: str) -> RunCandidate:
        return _run_detail(self.get(f"series/{run_id}/", lookup=True))

    def run_for_comicvine(self, comicvine_id: str) -> RunCandidate | None:
        results = self.get("series/", {"cv_id": comicvine_id}, lookup=True).get("results") or []
        return self.get_run(str(results[0]["id"])) if results else None

    def list_issues(self, run_id: str) -> list[IssueRef]:
        return [_issue(item, run_id) for item in self._pages("issue/", {"series_id": run_id}, lookup=True)]

    def get_issue(self, issue_id: str) -> IssueRef:
        item = self.get(f"issue/{issue_id}/", lookup=True)
        return _issue(item, str((item.get("series") or {}).get("id", "")))

    def issue_for_comicvine(self, comicvine_issue_id: str) -> IssueRef | None:
        results = self.get("issue/", {"cv_id": comicvine_issue_id}, lookup=True).get("results") or []
        return self.get_issue(str(results[0]["id"])) if results else None


def _run_summary(item: dict[str, Any]) -> RunCandidate:
    """The list endpoint: ``series`` is the display name "Batman (2016)";
    publisher, type and the Comic Vine/GCD bridges are already there."""
    display = str(item.get("series") or item.get("name") or "")
    name = display.rsplit(" (", 1)[0] if display.endswith(")") and " (" in display else display
    return _run_detail({**item, "name": name})


def _run_detail(item: dict[str, Any]) -> RunCandidate:
    links = {"metron": str(item["id"])}
    if item.get("cv_id"):
        links["comicvine"] = str(item["cv_id"])
    if item.get("gcd_id"):
        links["gcd"] = str(item["gcd_id"])
    series_type = str((item.get("series_type") or {}).get("name") or "").lower()
    return RunCandidate(
        provider="metron",
        id=str(item["id"]),
        name=str(item.get("name") or ""),
        start_year=item.get("year_began"),
        end_year=item.get("year_end"),
        publisher=(item.get("publisher") or {}).get("name"),
        issue_count=item.get("issue_count"),
        aliases=[a.get("series", "") for a in item.get("associated") or [] if a.get("series")],
        format=_SERIES_TYPES.get(series_type, "issue"),
        volume=str(item["volume"]) if item.get("volume") is not None else None,
        status=(item.get("status") or None) if isinstance(item.get("status"), str) else None,
        summary=item.get("desc"),
        url=item.get("resource_url"),
        links=links,
    )


def _issue(item: dict[str, Any], run_id: str) -> IssueRef:
    links = {"metron": str(item["id"])}
    if item.get("cv_id"):
        links["comicvine"] = str(item["cv_id"])
    if item.get("gcd_id"):
        links["gcd"] = str(item["gcd_id"])
    cover_date = item.get("cover_date")
    return IssueRef(
        provider="metron",
        id=str(item["id"]),
        run_id=str((item.get("series") or {}).get("id") or run_id),
        number=str(item["number"]).strip() if item.get("number") not in (None, "") else None,
        name=(item.get("name") or [None])[0] if isinstance(item.get("name"), list) else item.get("name"),
        year=int(cover_date[:4]) if cover_date and cover_date[:4].isdigit() else None,
        cover_date=cover_date,
        cover_url=item.get("image"),
        cover_hash=item.get("cover_hash"),
        page_count=item.get("page"),
        links=links,
    )
