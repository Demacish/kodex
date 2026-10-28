"""qBittorrent WebUI API v2 client — see kodex/acquire/clients/base.py's module
docstring for why this is never actually exercised against a real
instance in this environment. Every method takes an injectable `client`
(same convention as app/enrichment/*.py's providers) so tests can pass a
fake httpx.Client.

Session-cookie auth (WebUI's /api/v2/auth/login), not re-logging in on
every call — a QBittorrentClient instance holds its login for its whole
lifetime, matching how it's actually used (one instance per job, not a
shared singleton — see kodex/acquire/clients/manager.py).
"""

from __future__ import annotations

import re

import httpx

from kodex.acquire.clients.base import DownloadClientError, DownloadClientStatus

_MAGNET_BTIH_RE = re.compile(r"xt=urn:btih:([A-Za-z0-9]+)", re.IGNORECASE)


def extract_magnet_hash(magnet_uri: str) -> str | None:
    """A magnet URI's own btih hash IS the torrent's infohash — extractable
    client-side, unlike qBittorrent's /torrents/add response, which
    returns no identifier at all (a long-standing WebUI API limitation).
    This is how QBittorrentClient.add gets an external_id back for a
    magnet link; a plain .torrent-file URL has no equivalent client-side
    shortcut and isn't supported by add() below yet (would need to
    download and parse the torrent file's own bencoded info-hash first —
    left as a follow-up, see the open questions in
    claude/omnibus-och-ai-forbattringar.md).
    """
    match = _MAGNET_BTIH_RE.search(magnet_uri)
    return match.group(1).lower() if match else None


class QBittorrentClient:
    def __init__(self, base_url: str, username: str, password: str, *, client: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._client = client or httpx.Client(timeout=30.0)
        self._owns_client = client is None
        self._logged_in = False

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _login(self) -> None:
        if self._logged_in:
            return
        try:
            response = self._client.post(
                f"{self.base_url}/api/v2/auth/login", data={"username": self._username, "password": self._password}
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DownloadClientError(f"qBittorrent login request failed: {exc}") from exc
        if response.text.strip() != "Ok.":
            raise DownloadClientError("qBittorrent login rejected (wrong username/password?)")
        self._logged_in = True

    def add_magnet(self, magnet_uri: str, *, save_path: str) -> str:
        """Adds a magnet link, returns its infohash as the external_id —
        see extract_magnet_hash's docstring for why that (not qBittorrent's
        own response) is the id source.
        """
        external_id = extract_magnet_hash(magnet_uri)
        if external_id is None:
            raise DownloadClientError("Not a magnet URI with a btih hash — plain .torrent URLs aren't supported yet")

        self._login()
        try:
            response = self._client.post(
                f"{self.base_url}/api/v2/torrents/add", data={"urls": magnet_uri, "savepath": save_path}
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DownloadClientError(f"qBittorrent add request failed: {exc}") from exc
        if response.text.strip() != "Ok.":
            raise DownloadClientError(f"qBittorrent rejected the torrent: {response.text.strip()}")
        return external_id

    def get_status(self, torrent_hash: str) -> DownloadClientStatus:
        self._login()
        try:
            response = self._client.get(f"{self.base_url}/api/v2/torrents/info", params={"hashes": torrent_hash})
            response.raise_for_status()
            results = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DownloadClientError(f"qBittorrent status request failed: {exc}") from exc

        if not results:
            return DownloadClientStatus(
                progress=0.0, is_complete=False, save_path=None, error="Torrent not found in qBittorrent"
            )
        torrent = results[0]
        state = torrent.get("state", "")
        is_complete = state in {"uploading", "stalledUP", "pausedUP", "queuedUP", "forcedUP"}
        return DownloadClientStatus(
            progress=float(torrent.get("progress", 0.0)),
            is_complete=is_complete,
            save_path=torrent.get("save_path") or torrent.get("content_path"),
            error=torrent.get("last_error") or None if state == "error" else None,
            content_path=torrent.get("content_path") or None,
        )

    def remove(self, torrent_hash: str, *, delete_files: bool = False) -> None:
        self._login()
        try:
            response = self._client.post(
                f"{self.base_url}/api/v2/torrents/delete",
                data={"hashes": torrent_hash, "deleteFiles": str(delete_files).lower()},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DownloadClientError(f"qBittorrent delete request failed: {exc}") from exc
