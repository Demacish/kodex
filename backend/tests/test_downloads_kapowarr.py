"""Tests for kodex/acquire/clients/kapowarr.py — same injectable-fake-client
convention as test_downloads_qbittorrent.py. Kapowarr's exact API shape
is unverified against a live instance (see the module's own docstring).
"""

from __future__ import annotations

import httpx
import pytest

from kodex.acquire.clients.base import DownloadClientError
from kodex.acquire.clients.kapowarr import add_volume


class _FakeResponse:
    def raise_for_status(self) -> None:
        pass


class _FakeClient:
    def __init__(self, *, raise_error: Exception | None = None) -> None:
        self.raise_error = raise_error
        self.calls: list[dict] = []

    def post(self, url, *, params=None, json=None):
        self.calls.append({"url": url, "params": params, "json": json})
        if self.raise_error is not None:
            raise self.raise_error
        return _FakeResponse()

    def close(self):
        pass


def test_add_volume_succeeds():
    fake = _FakeClient()
    add_volume("12345", base_url="http://kapowarr.example:5656", api_key="key", root_folder_id="1", client=fake)

    assert fake.calls[0]["json"] == {"comicvine_id": "cv:12345", "root_folder_id": 1, "monitor": True}
    assert fake.calls[0]["params"] == {"api_key": "key"}


def test_add_volume_raises_when_not_configured():
    with pytest.raises(DownloadClientError):
        add_volume("12345", base_url="", api_key="", root_folder_id="1", client=_FakeClient())


def test_add_volume_raises_when_root_folder_missing():
    with pytest.raises(DownloadClientError):
        add_volume(
            "12345", base_url="http://kapowarr.example:5656", api_key="key", root_folder_id="", client=_FakeClient()
        )


def test_add_volume_raises_when_root_folder_is_not_an_integer():
    with pytest.raises(DownloadClientError):
        add_volume(
            "12345",
            base_url="http://kapowarr.example:5656",
            api_key="key",
            root_folder_id="not-a-number",
            client=_FakeClient(),
        )


def test_add_volume_raises_on_http_error():
    fake = _FakeClient(raise_error=httpx.ConnectError("down", request=None))
    with pytest.raises(DownloadClientError):
        add_volume("12345", base_url="http://kapowarr.example:5656", api_key="key", root_folder_id="1", client=fake)
