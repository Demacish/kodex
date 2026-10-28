"""Comic Vine (https://comicvine.gamespot.com/api/): runs ("volumes"),
their issue lists and single issues.

Terms that shape this client: non-commercial use only, a link back to
Comic Vine wherever its data is shown, 200 calls per resource and hour
(tracked per endpoint here), no bursts, and responses should be cached.
"""

from __future__ import annotations

from typing import Any

from kodex.matching.providers.base import (
    IssueRef,
    NotConfigured,
    NotFound,
    ProviderClient,
    ProviderError,
    RateLimited,
    RatePolicy,
    RunCandidate,
)

_HOUR = 3600.0
_PER_RESOURCE = RatePolicy(min_interval=0, window=_HOUR, window_limit=200)
_RUN_FIELDS = "id,name,start_year,publisher,count_of_issues,aliases,image,site_detail_url"
_ISSUE_FIELDS = "id,issue_number,cover_date,name,image,volume"


class ComicVine(ProviderClient):
    name = "comicvine"
    base_url = "https://comicvine.gamespot.com/api/"
    secret_params = frozenset({"api_key"})
    # One call a second at most; bursts get temporarily blocked.
    default_policy = RatePolicy(min_interval=1.0)
    bucket_policies = {
        "search": _PER_RESOURCE,
        "volume": _PER_RESOURCE,
        "volumes": _PER_RESOURCE,
        "issues": _PER_RESOURCE,
        "issue": _PER_RESOURCE,
    }

    def __init__(self, *, api_key: str, **kwargs: Any) -> None:
        if not api_key:
            raise NotConfigured("comicvine: COMICVINE_API_KEY is not set")
        self.api_key = api_key
        super().__init__(**kwargs)

    def auth_params(self) -> dict[str, str]:
        return {"api_key": self.api_key}

    def check_payload(self, payload: Any) -> None:
        status = payload.get("status_code") if isinstance(payload, dict) else None
        if status in (1, None):
            return
        if status == 101:
            raise NotFound(f"comicvine: {payload.get('error')}")
        if status == 100:
            raise NotConfigured("comicvine: invalid API key")
        if status == 107:
            raise RateLimited("comicvine", _in_an_hour())
        raise ProviderError(f"comicvine: {payload.get('error')} (status {status})")

    def search_runs(self, query: str, *, limit: int = 100) -> list[RunCandidate]:
        """Runs matching ``query``, in Comic Vine's relevance order. The
        search index has stale fields (an issue count of 0, no publisher,
        a blank cover), so the details come from the volumes endpoint, one
        call for every 100 hits."""
        payload = self.get(
            "search/",
            {"format": "json", "resources": "volume", "query": query, "field_list": "id", "limit": str(limit)},
            bucket="search",
        )
        ids = [str(item["id"]) for item in payload.get("results") or [] if item.get("id")]
        return self.get_runs(ids)

    def get_runs(self, run_ids: list[str]) -> list[RunCandidate]:
        details: dict[str, RunCandidate] = {}
        for start in range(0, len(run_ids), 100):
            chunk = run_ids[start : start + 100]
            payload = self.get(
                "volumes/",
                {"format": "json", "filter": f"id:{'|'.join(chunk)}", "field_list": _RUN_FIELDS, "limit": "100"},
                bucket="volumes",
                lookup=True,
            )
            details.update({run.id: run for run in (_run(item) for item in payload.get("results") or [])})
        return [details[run_id] for run_id in run_ids if run_id in details]

    def get_run(self, run_id: str) -> RunCandidate:
        payload = self.get(
            f"volume/4050-{run_id}/", {"format": "json", "field_list": _RUN_FIELDS}, bucket="volume", lookup=True
        )
        return _run(payload["results"])

    def list_issues(self, run_id: str) -> list[IssueRef]:
        issues: list[IssueRef] = []
        offset = 0
        while True:
            payload = self.get(
                "issues/",
                {"format": "json", "filter": f"volume:{run_id}", "field_list": _ISSUE_FIELDS, "limit": "100",
                 "offset": str(offset), "sort": "id:asc"},
                bucket="issues",
                lookup=True,
            )  # fmt: skip
            page = payload.get("results") or []
            issues += [_issue(item, run_id) for item in page]
            offset += len(page)
            if not page or offset >= int(payload.get("number_of_total_results") or 0):
                return issues

    def get_issue(self, issue_id: str) -> IssueRef:
        payload = self.get(
            f"issue/4000-{issue_id}/", {"format": "json", "field_list": _ISSUE_FIELDS}, bucket="issue", lookup=True
        )
        item = payload["results"]
        return _issue(item, str((item.get("volume") or {}).get("id", "")))


def _in_an_hour() -> Any:
    import datetime as dt

    return dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)


def _year(value: Any) -> int | None:
    text = str(value or "").strip()
    return int(text[:4]) if text[:4].isdigit() else None


def _run(item: dict[str, Any]) -> RunCandidate:
    aliases = [a.strip() for a in str(item.get("aliases") or "").splitlines() if a.strip()]
    image = item.get("image") or {}
    return RunCandidate(
        provider="comicvine",
        id=str(item["id"]),
        name=str(item.get("name") or ""),
        start_year=_year(item.get("start_year")),
        publisher=(item.get("publisher") or {}).get("name"),
        issue_count=item.get("count_of_issues"),
        aliases=aliases,
        cover_url=image.get("original_url") or image.get("medium_url"),
        url=item.get("site_detail_url"),
        links={"comicvine": str(item["id"])},
    )


def _issue(item: dict[str, Any], run_id: str) -> IssueRef:
    image = item.get("image") or {}
    number = item.get("issue_number")
    return IssueRef(
        provider="comicvine",
        id=str(item["id"]),
        run_id=str((item.get("volume") or {}).get("id") or run_id),
        number=str(number).strip() if number not in (None, "") else None,
        name=item.get("name"),
        year=_year(item.get("cover_date")),
        cover_date=item.get("cover_date"),
        cover_url=image.get("original_url") or image.get("medium_url"),
        links={"comicvine": str(item["id"])},
    )
