"""Tests for app/enrichment/story_arc_roster.py's fetch_arc_name (C15) —
a minimal fake httpx.Client, same injectable-client convention as every
other enrichment provider (see e.g. test_ai_providers.py).
"""

from __future__ import annotations

import httpx

from app.enrichment.story_arc_roster import fetch_arc_name


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
        self.calls: list[str] = []

    def get(self, url, *, params=None):
        self.calls.append(url)
        if self.raise_error is not None:
            raise self.raise_error
        return self.response

    def close(self) -> None:
        pass


def test_fetch_arc_name_returns_name():
    fake = _FakeClient(_FakeResponse({"results": {"id": 123, "name": "Silent Tides"}}))
    assert fetch_arc_name(123, "fake-key", client=fake) == "Silent Tides"


def test_fetch_arc_name_returns_none_on_http_error():
    fake = _FakeClient(raise_error=httpx.ConnectError("down", request=None))
    assert fetch_arc_name(123, "fake-key", client=fake) is None


def test_fetch_arc_name_returns_none_when_results_empty():
    fake = _FakeClient(_FakeResponse({"results": None}))
    assert fetch_arc_name(123, "fake-key", client=fake) is None
