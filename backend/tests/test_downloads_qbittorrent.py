"""Tests for kodex/acquire/clients/qbittorrent.py — same injectable-fake-client
convention as app/enrichment/*.py's providers (see test_ai_providers.py).
"""

from __future__ import annotations

import httpx
import pytest

from kodex.acquire.clients.base import DownloadClientError
from kodex.acquire.clients.qbittorrent import QBittorrentClient, extract_magnet_hash

MAGNET = "magnet:?xt=urn:btih:ABCDEF1234567890ABCDEF1234567890ABCDEF12&dn=Some+Comic"


class _FakeResponse:
    def __init__(self, text: str = "Ok.", json_data=None, status_code: int = 200) -> None:
        self.text = text
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)  # type: ignore[arg-type]

    def json(self):
        return self._json_data


class _FakeClient:
    def __init__(
        self, responses: dict[str, _FakeResponse] | None = None, *, raise_error: Exception | None = None
    ) -> None:
        self.responses = responses or {}
        self.raise_error = raise_error
        self.calls: list[tuple[str, dict]] = []

    def post(self, url, *, data=None):
        self.calls.append((url, data or {}))
        if self.raise_error is not None:
            raise self.raise_error
        for key, response in self.responses.items():
            if key in url:
                return response
        return _FakeResponse()

    def get(self, url, *, params=None):
        self.calls.append((url, params or {}))
        if self.raise_error is not None:
            raise self.raise_error
        for key, response in self.responses.items():
            if key in url:
                return response
        return _FakeResponse()


def test_extract_magnet_hash():
    assert extract_magnet_hash(MAGNET) == "abcdef1234567890abcdef1234567890abcdef12"


def test_extract_magnet_hash_returns_none_without_btih():
    assert extract_magnet_hash("magnet:?dn=no-hash-here") is None


def test_add_magnet_logs_in_and_returns_hash():
    fake = _FakeClient({"auth/login": _FakeResponse("Ok."), "torrents/add": _FakeResponse("Ok.")})
    qbt = QBittorrentClient("http://qbt.example:8080", "admin", "adminadmin", client=fake)

    external_id = qbt.add_magnet(MAGNET, save_path="/downloads")

    assert external_id == "abcdef1234567890abcdef1234567890abcdef12"
    assert any("auth/login" in url for url, _ in fake.calls)


def test_add_magnet_raises_without_btih_hash():
    fake = _FakeClient({"auth/login": _FakeResponse("Ok.")})
    qbt = QBittorrentClient("http://qbt.example:8080", "admin", "adminadmin", client=fake)
    with pytest.raises(DownloadClientError):
        qbt.add_magnet("magnet:?dn=no-hash", save_path="/downloads")


def test_add_magnet_raises_on_login_failure():
    fake = _FakeClient({"auth/login": _FakeResponse("Fails.")})
    qbt = QBittorrentClient("http://qbt.example:8080", "admin", "wrong", client=fake)
    with pytest.raises(DownloadClientError):
        qbt.add_magnet(MAGNET, save_path="/downloads")


def test_add_magnet_raises_on_http_error():
    fake = _FakeClient(raise_error=httpx.ConnectError("down", request=None))
    qbt = QBittorrentClient("http://qbt.example:8080", "admin", "adminadmin", client=fake)
    with pytest.raises(DownloadClientError):
        qbt.add_magnet(MAGNET, save_path="/downloads")


def test_get_status_complete():
    fake = _FakeClient(
        {
            "auth/login": _FakeResponse("Ok."),
            "torrents/info": _FakeResponse(
                json_data=[{"state": "uploading", "progress": 1.0, "save_path": "/downloads/x"}]
            ),
        }
    )
    qbt = QBittorrentClient("http://qbt.example:8080", "admin", "adminadmin", client=fake)

    status = qbt.get_status("abc123")

    assert status.is_complete is True
    assert status.progress == 1.0
    assert status.save_path == "/downloads/x"


def test_get_status_in_progress():
    fake = _FakeClient(
        {
            "auth/login": _FakeResponse("Ok."),
            "torrents/info": _FakeResponse(json_data=[{"state": "downloading", "progress": 0.42}]),
        }
    )
    qbt = QBittorrentClient("http://qbt.example:8080", "admin", "adminadmin", client=fake)

    status = qbt.get_status("abc123")

    assert status.is_complete is False
    assert status.progress == 0.42


def test_get_status_not_found():
    fake = _FakeClient({"auth/login": _FakeResponse("Ok."), "torrents/info": _FakeResponse(json_data=[])})
    qbt = QBittorrentClient("http://qbt.example:8080", "admin", "adminadmin", client=fake)

    status = qbt.get_status("missing")

    assert status.error is not None


def test_remove_sends_delete_request():
    fake = _FakeClient({"auth/login": _FakeResponse("Ok."), "torrents/delete": _FakeResponse("Ok.")})
    qbt = QBittorrentClient("http://qbt.example:8080", "admin", "adminadmin", client=fake)

    qbt.remove("abc123")

    assert any("torrents/delete" in url for url, _ in fake.calls)
