"""Tests for kodex/acquire/clients/mylar3.py — same injectable-fake-client
convention as test_downloads_qbittorrent.py. Mylar3's exact API shape is
unverified against a live instance (see the module's own docstring).
"""

from __future__ import annotations

import httpx
import pytest

from kodex.acquire.clients.base import DownloadClientError
from kodex.acquire.clients.mylar3 import add_comic


class _FakeResponse:
    def __init__(self, json_data: dict, status_code: int = 200) -> None:
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)  # type: ignore[arg-type]

    def json(self) -> dict:
        return self._json_data


class _FakeClient:
    def __init__(self, response: _FakeResponse | None = None, *, raise_error: Exception | None = None) -> None:
        self.response = response
        self.raise_error = raise_error
        self.calls: list[dict] = []

    def get(self, url, *, params=None):
        self.calls.append(params or {})
        if self.raise_error is not None:
            raise self.raise_error
        return self.response

    def close(self):
        pass


def test_add_comic_succeeds():
    fake = _FakeClient(_FakeResponse({"success": True}))
    add_comic("12345", base_url="http://mylar3.example:8090", api_key="key", client=fake)
    assert fake.calls[0]["cmd"] == "addComic"
    assert fake.calls[0]["id"] == "12345"


def test_add_comic_raises_when_not_configured():
    with pytest.raises(DownloadClientError):
        add_comic("12345", base_url="", api_key="", client=_FakeClient())


def test_add_comic_raises_on_explicit_rejection():
    fake = _FakeClient(_FakeResponse({"success": False, "error": "not found"}))
    with pytest.raises(DownloadClientError):
        add_comic("12345", base_url="http://mylar3.example:8090", api_key="key", client=fake)


def test_add_comic_raises_on_http_error():
    fake = _FakeClient(raise_error=httpx.ConnectError("down", request=None))
    with pytest.raises(DownloadClientError):
        add_comic("12345", base_url="http://mylar3.example:8090", api_key="key", client=fake)
