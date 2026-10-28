"""Tests for kodex/acquire/clients/annas_archive.py — see that module's docstring
for why its HTML parsing is unverified against a real page in this
environment (no network access here).
"""

from __future__ import annotations

import httpx
import pytest

from kodex.acquire.clients.annas_archive import parse_mirrors, search
from kodex.acquire.clients.base import DownloadClientError

_SAMPLE_HTML = """
<div class="result">
  <a href="/md5/abcdef0123456789abcdef0123456789">Absolute Corvid Vol 1</a>
</div>
<div class="result">
  <a href="/md5/11111111111111111111111111111111"><div>Absolute Corvid Vol 2</div></a>
</div>
"""


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)  # type: ignore[arg-type]


class _FakeClient:
    def __init__(
        self, responses: dict[str, _FakeResponse] | None = None, *, raise_error: Exception | None = None
    ) -> None:
        self.responses = responses or {}
        self.raise_error = raise_error
        self.calls: list[str] = []

    def get(self, url, *, params=None):
        self.calls.append(url)
        if self.raise_error is not None:
            raise self.raise_error
        return self.responses[url]


def test_parse_mirrors_splits_and_strips():
    assert parse_mirrors(" http://a.example/ , http://b.example ") == ["http://a.example", "http://b.example"]


def test_parse_mirrors_empty_string_is_empty_list():
    assert parse_mirrors("") == []


def test_search_parses_results_from_first_mirror():
    fake = _FakeClient({"http://a.example/search": _FakeResponse(_SAMPLE_HTML)})

    results = search("Absolute Corvid", mirrors=["http://a.example"], client=fake)

    assert len(results) == 2
    assert results[0].title == "Absolute Corvid Vol 1"
    assert results[0].detail_url == "http://a.example/md5/abcdef0123456789abcdef0123456789"
    assert results[1].title == "Absolute Corvid Vol 2"


def test_search_falls_back_to_next_mirror_on_failure():
    class _PartialFailClient(_FakeClient):
        def get(self, url, *, params=None):
            if "a.example" in url:
                raise httpx.ConnectError("down", request=None)
            return super().get(url, params=params)

    partial = _PartialFailClient({"http://b.example/search": _FakeResponse(_SAMPLE_HTML)})

    results = search("query", mirrors=["http://a.example", "http://b.example"], client=partial)

    assert len(results) == 2


def test_search_raises_when_no_mirrors_configured():
    with pytest.raises(DownloadClientError):
        search("query", mirrors=[], client=_FakeClient())


def test_search_raises_when_all_mirrors_fail():
    fake = _FakeClient(raise_error=httpx.ConnectError("down", request=None))
    with pytest.raises(DownloadClientError):
        search("query", mirrors=["http://a.example", "http://b.example"], client=fake)
