from __future__ import annotations

import httpx
import pytest

from kodex.acquire.clients.base import DownloadClientError
from kodex.acquire.clients.flaresolverr import FlareSolverrClient


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
    def __init__(self, responses_by_cmd: dict[str, _FakeResponse], *, raise_error: Exception | None = None) -> None:
        self.responses_by_cmd = responses_by_cmd
        self.raise_error = raise_error
        self.calls: list[dict] = []

    def post(self, url, *, json=None):
        self.calls.append(json or {})
        if self.raise_error is not None:
            raise self.raise_error
        return self.responses_by_cmd[json["cmd"]]

    def close(self):
        pass


def test_solve_creates_session_then_solves():
    fake = _FakeClient(
        {
            "sessions.create": _FakeResponse({"status": "ok"}),
            "request.get": _FakeResponse({"status": "ok", "solution": {"response": "<html>ok</html>"}}),
        }
    )
    solver = FlareSolverrClient("http://flaresolverr:8191", client=fake)

    html = solver.solve("https://getcomics.org/?s=batman")

    assert html == "<html>ok</html>"
    assert fake.calls[0]["cmd"] == "sessions.create"
    assert fake.calls[1]["session"] == fake.calls[0]["session"]


def test_solve_reuses_session_across_calls():
    fake = _FakeClient(
        {
            "sessions.create": _FakeResponse({"status": "ok"}),
            "request.get": _FakeResponse({"status": "ok", "solution": {"response": "<html></html>"}}),
        }
    )
    solver = FlareSolverrClient("http://flaresolverr:8191", client=fake)

    solver.solve("https://getcomics.org/?s=batman")
    solver.solve("https://getcomics.org/?s=superman")

    create_calls = [c for c in fake.calls if c["cmd"] == "sessions.create"]
    assert len(create_calls) == 1


def test_solve_raises_on_rejected_status():
    fake = _FakeClient({"sessions.create": _FakeResponse({"status": "error", "message": "browser crashed"})})
    solver = FlareSolverrClient("http://flaresolverr:8191", client=fake)
    with pytest.raises(DownloadClientError):
        solver.solve("https://getcomics.org/?s=batman")


def test_solve_raises_on_http_error():
    fake = _FakeClient({}, raise_error=httpx.ConnectError("down", request=None))
    solver = FlareSolverrClient("http://flaresolverr:8191", client=fake)
    with pytest.raises(DownloadClientError):
        solver.solve("https://getcomics.org/?s=batman")


def test_close_destroys_session_when_one_was_created():
    fake = _FakeClient(
        {
            "sessions.create": _FakeResponse({"status": "ok"}),
            "request.get": _FakeResponse({"status": "ok", "solution": {"response": "<html></html>"}}),
            "sessions.destroy": _FakeResponse({"status": "ok"}),
        }
    )
    solver = FlareSolverrClient("http://flaresolverr:8191", client=fake)
    solver.solve("https://getcomics.org/?s=batman")

    solver.close()

    assert any(c["cmd"] == "sessions.destroy" for c in fake.calls)


def test_close_is_a_noop_when_no_session_was_created():
    fake = _FakeClient({})
    solver = FlareSolverrClient("http://flaresolverr:8191", client=fake)

    solver.close()  # must not raise even though no session exists

    assert fake.calls == []
