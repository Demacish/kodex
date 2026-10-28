"""Tests for kodex/acquire/clients/sabnzbd.py — same fake-client convention as
test_downloads_qbittorrent.py.
"""

from __future__ import annotations

import httpx
import pytest

from kodex.acquire.clients.base import DownloadClientError
from kodex.acquire.clients.sabnzbd import SabnzbdClient


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
    def __init__(self, responses_by_mode: dict[str, _FakeResponse], *, raise_error: Exception | None = None) -> None:
        self.responses_by_mode = responses_by_mode
        self.raise_error = raise_error
        self.calls: list[dict] = []

    def get(self, url, *, params=None):
        self.calls.append(params or {})
        if self.raise_error is not None:
            raise self.raise_error
        return self.responses_by_mode[params["mode"]]


def test_add_url_returns_nzo_id():
    fake = _FakeClient({"addurl": _FakeResponse({"status": True, "nzo_ids": ["SABnzbd_nzo_123"]})})
    sab = SabnzbdClient("http://sab.example:8080", "fake-key", client=fake)

    assert sab.add_url("http://indexer.example/x.nzb") == "SABnzbd_nzo_123"


def test_add_url_raises_when_rejected():
    fake = _FakeClient({"addurl": _FakeResponse({"status": False, "error": "bad nzb"})})
    sab = SabnzbdClient("http://sab.example:8080", "fake-key", client=fake)
    with pytest.raises(DownloadClientError):
        sab.add_url("http://indexer.example/x.nzb")


def test_add_url_raises_on_http_error():
    fake = _FakeClient({}, raise_error=httpx.ConnectError("down", request=None))
    sab = SabnzbdClient("http://sab.example:8080", "fake-key", client=fake)
    with pytest.raises(DownloadClientError):
        sab.add_url("http://indexer.example/x.nzb")


def test_get_status_found_in_history_success():
    fake = _FakeClient(
        {
            "history": _FakeResponse(
                {"history": {"slots": [{"nzo_id": "abc", "status": "Completed", "storage": "/downloads/x"}]}}
            ),
        }
    )
    sab = SabnzbdClient("http://sab.example:8080", "fake-key", client=fake)

    status = sab.get_status("abc")

    assert status.is_complete is True
    assert status.progress == 1.0
    assert status.save_path == "/downloads/x"


def test_get_status_found_in_history_failed():
    fake = _FakeClient(
        {
            "history": _FakeResponse(
                {"history": {"slots": [{"nzo_id": "abc", "status": "Failed", "fail_message": "oops"}]}}
            ),
        }
    )
    sab = SabnzbdClient("http://sab.example:8080", "fake-key", client=fake)

    status = sab.get_status("abc")

    assert status.is_complete is False
    assert status.error == "oops"


def test_get_status_found_in_queue():
    fake = _FakeClient(
        {
            "history": _FakeResponse({"history": {"slots": []}}),
            "queue": _FakeResponse({"queue": {"slots": [{"nzo_id": "abc", "percentage": "55"}]}}),
        }
    )
    sab = SabnzbdClient("http://sab.example:8080", "fake-key", client=fake)

    status = sab.get_status("abc")

    assert status.is_complete is False
    assert status.progress == pytest.approx(0.55)


def test_get_status_not_found_anywhere():
    fake = _FakeClient(
        {
            "history": _FakeResponse({"history": {"slots": []}}),
            "queue": _FakeResponse({"queue": {"slots": []}}),
        }
    )
    sab = SabnzbdClient("http://sab.example:8080", "fake-key", client=fake)

    status = sab.get_status("missing")

    assert status.error is not None


def test_remove_sends_delete_request():
    fake = _FakeClient({"queue_delete": _FakeResponse({"status": True})})
    sab = SabnzbdClient("http://sab.example:8080", "fake-key", client=fake)

    sab.remove("abc")

    assert fake.calls[0]["mode"] == "queue_delete"
