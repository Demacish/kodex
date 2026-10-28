"""Tests for kodex/acquire/clients/prowlarr.py — same injectable-fake-client
convention as test_downloads_qbittorrent.py.
"""

from __future__ import annotations

import httpx
import pytest

from kodex.acquire.clients.base import DownloadClientError
from kodex.acquire.clients.prowlarr import search


class _FakeResponse:
    def __init__(self, json_data, status_code: int = 200) -> None:
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)  # type: ignore[arg-type]

    def json(self):
        return self._json_data


class _FakeClient:
    def __init__(self, response: _FakeResponse | None = None, *, raise_error: Exception | None = None) -> None:
        self.response = response
        self.raise_error = raise_error
        self.calls: list[dict] = []

    def get(self, url, *, params=None, headers=None):
        self.calls.append({"params": params, "headers": headers})
        if self.raise_error is not None:
            raise self.raise_error
        return self.response


def test_search_normalizes_torrent_and_usenet_results():
    fake = _FakeClient(
        _FakeResponse(
            [
                {
                    "title": "Absolute Corvid 001",
                    "magnetUrl": "magnet:?xt=urn:btih:abc",
                    "protocol": "torrent",
                    "indexer": "X",
                    "size": 123,
                    "publishDate": "2026-01-01",
                },
                {
                    "title": "Absolute Corvid 002",
                    "downloadUrl": "http://sab/x.nzb",
                    "protocol": "usenet",
                    "indexer": "Y",
                    "size": 456,
                    "publishDate": None,
                },
            ]
        )
    )

    results = search("Absolute Corvid", base_url="http://prowlarr", api_key="key", client=fake)

    assert len(results) == 2
    assert results[0].download_url == "magnet:?xt=urn:btih:abc"
    assert results[0].protocol == "torrent"
    assert results[1].download_url == "http://sab/x.nzb"
    assert results[1].protocol == "usenet"
    assert fake.calls[0]["headers"] == {"X-Api-Key": "key"}


def test_search_skips_results_missing_a_usable_download_url():
    fake = _FakeClient(_FakeResponse([{"title": "No link", "protocol": "torrent", "indexer": "X"}]))

    results = search("query", base_url="http://prowlarr", api_key="key", client=fake)

    assert results == []


def test_search_skips_results_with_unknown_protocol():
    fake = _FakeClient(
        _FakeResponse([{"title": "Weird", "downloadUrl": "http://x", "protocol": "ftp", "indexer": "X"}])
    )

    results = search("query", base_url="http://prowlarr", api_key="key", client=fake)

    assert results == []


def test_search_raises_when_not_configured():
    with pytest.raises(DownloadClientError):
        search("query", base_url="", api_key="", client=_FakeClient())


def test_search_raises_on_http_error():
    fake = _FakeClient(raise_error=httpx.ConnectError("down", request=None))
    with pytest.raises(DownloadClientError):
        search("query", base_url="http://prowlarr", api_key="key", client=fake)
