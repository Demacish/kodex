"""FlareSolverr client (C12) — solves Cloudflare challenges via a
headless-Chromium proxy so kodex/acquire/clients/scrapers/getcomics.py can read
pages a plain httpx GET would just get a challenge page back from. See
kodex/acquire/clients/base.py's module docstring for the general "never actually
reachable in this deployment" caveat.

One named session per FlareSolverrClient instance, created lazily on the
first solve() and reused for every subsequent one — a fresh Cloudflare
solve costs 5-15s of headless-Chromium time, and reusing the session's
cookies avoids paying that cost again for every page in one scrape run.
Callers are expected to close() when done (context-manager style is
overkill here — see kodex/acquire/clients/scrapers/getcomics.py's single call
site) to destroy the session server-side rather than leaking it.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from kodex.acquire.clients.base import DownloadClientError


class FlareSolverrClient:
    def __init__(self, base_url: str, *, client: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=90.0)  # a solve can legitimately take tens of seconds
        self._owns_client = client is None
        self._session_id: str | None = None

    def close(self) -> None:
        if self._session_id is not None:
            try:
                self._post({"cmd": "sessions.destroy", "session": self._session_id})
            except DownloadClientError:
                pass  # best-effort cleanup — a failed destroy shouldn't mask the caller's own result/error
            self._session_id = None
        if self._owns_client:
            self._client.close()

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.post(f"{self.base_url}/v1", json=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DownloadClientError(f"FlareSolverr request failed: {exc}") from exc
        if body.get("status") != "ok":
            raise DownloadClientError(f"FlareSolverr rejected the request: {body.get('message', 'unknown error')}")
        found: dict[str, Any] = body
        return found

    def _ensure_session(self) -> str:
        if self._session_id is None:
            session_id = f"kodex-{uuid.uuid4().hex[:12]}"
            self._post({"cmd": "sessions.create", "session": session_id})
            self._session_id = session_id
        return self._session_id

    def solve(self, url: str) -> str:
        """Returns the solved page's HTML."""
        session_id = self._ensure_session()
        body = self._post({"cmd": "request.get", "url": url, "session": session_id})
        return str(body["solution"]["response"])
