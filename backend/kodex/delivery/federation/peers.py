"""The other servers, as KODEX_PEERS lists them, and how this one talks to them."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = 5.0
# A whole archive over a VPN can take a while.
_UPLOAD_TIMEOUT = 600.0


class PeerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Peer:
    name: str
    url: str
    upload_key: str

    def _headers(self) -> dict[str, str]:
        return {"X-Kodex-Upload-Key": self.upload_key}

    def _endpoint(self, path: str) -> str:
        return self.url.rstrip("/") + path

    def libraries(self) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = self._request("GET", "/federation/libraries")
        return found

    def presence(self, items: list[dict[str, Any]]) -> list[bool]:
        """Which of these books (content_hash, series_title, number,
        edition_type) the other server already has, in the same order."""
        response = self._request("POST", "/federation/presence", json={"books": items})
        return [bool(p) for p in response["present"]]

    def upload(self, library_id: int, path: Path, *, upload_name: str, subfolder: str, rescan: bool) -> str:
        """Uploads one file: "copied", or "exists" when the other server
        already has a file by that name there (HTTP 409)."""
        try:
            with path.open("rb") as handle:
                response = httpx.post(
                    self._endpoint(f"/libraries/{library_id}/upload"),
                    headers=self._headers(),
                    data={"subfolder": subfolder, "rescan": "true" if rescan else "false"},
                    files={"file": (upload_name, handle, "application/octet-stream")},
                    timeout=_UPLOAD_TIMEOUT,
                )
        except httpx.HTTPError as exc:
            raise PeerError(f"{self.name}: {exc}") from exc
        if response.status_code == 409:
            return "exists"
        if response.status_code >= 400:
            raise PeerError(f"{self.name}: HTTP {response.status_code} {response.text[:200]}")
        return "copied"

    def scan(self, library_id: int) -> None:
        self._request("POST", f"/federation/libraries/{library_id}/scan")

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = httpx.request(method, self._endpoint(path), headers=self._headers(), timeout=_TIMEOUT, **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PeerError(f"{self.name}: {exc}") from exc


def configured_peers(settings: Settings | None = None) -> list[Peer]:
    raw = (settings or get_settings()).kodex_peers.strip()
    if not raw:
        return []
    try:
        entries = json.loads(raw)
        return [Peer(name=str(e["name"]), url=str(e["url"]), upload_key=str(e["upload_key"])) for e in entries]
    except (ValueError, TypeError, KeyError) as exc:
        logger.error("KODEX_PEERS is not a valid JSON list of {name, url, upload_key}: %s", exc)
        return []


def get_peer(name: str, settings: Settings | None = None) -> Peer | None:
    return next((peer for peer in configured_peers(settings) if peer.name == name), None)
