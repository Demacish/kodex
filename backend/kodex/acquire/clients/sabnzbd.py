"""SABnzbd API client — see kodex/acquire/clients/base.py's module docstring for
why this is never actually exercised against a real instance here.
Simpler than qbittorrent.py in one respect: SABnzbd's own addurl response
directly returns the nzo_id, no magnet-hash-extraction workaround needed.

A completed download moves from SABnzbd's queue into its history — so
get_status checks history first (an nzo_id found there is definitely
done), falling back to the queue for anything still in progress.
"""

from __future__ import annotations

import httpx

from kodex.acquire.clients.base import DownloadClientError, DownloadClientStatus


class SabnzbdClient:
    def __init__(self, base_url: str, api_key: str, *, client: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=30.0)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def add_url(self, nzb_url: str, *, category: str | None = None) -> str:
        params = {"mode": "addurl", "name": nzb_url, "apikey": self._api_key, "output": "json"}
        if category:
            params["cat"] = category
        try:
            response = self._client.get(f"{self.base_url}/api", params=params)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DownloadClientError(f"SABnzbd addurl request failed: {exc}") from exc

        if not data.get("status"):
            raise DownloadClientError(f"SABnzbd rejected the NZB: {data.get('error', 'unknown error')}")
        nzo_ids = data.get("nzo_ids") or []
        if not nzo_ids:
            raise DownloadClientError("SABnzbd accepted the NZB but returned no nzo_id")
        return str(nzo_ids[0])

    def get_status(self, nzo_id: str) -> DownloadClientStatus:
        try:
            history_response = self._client.get(
                f"{self.base_url}/api", params={"mode": "history", "apikey": self._api_key, "output": "json"}
            )
            history_response.raise_for_status()
            history = history_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DownloadClientError(f"SABnzbd history request failed: {exc}") from exc

        for entry in (history.get("history") or {}).get("slots", []):
            if entry.get("nzo_id") == nzo_id:
                failed = entry.get("status") == "Failed"
                return DownloadClientStatus(
                    progress=1.0,
                    is_complete=not failed,
                    save_path=entry.get("storage"),
                    error=entry.get("fail_message") or None if failed else None,
                    content_path=entry.get("storage"),
                )

        try:
            queue_response = self._client.get(
                f"{self.base_url}/api", params={"mode": "queue", "apikey": self._api_key, "output": "json"}
            )
            queue_response.raise_for_status()
            queue = queue_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DownloadClientError(f"SABnzbd queue request failed: {exc}") from exc

        for entry in (queue.get("queue") or {}).get("slots", []):
            if entry.get("nzo_id") == nzo_id:
                percentage = float(entry.get("percentage") or 0.0)
                return DownloadClientStatus(progress=percentage / 100.0, is_complete=False, save_path=None)

        return DownloadClientStatus(
            progress=0.0, is_complete=False, save_path=None, error="nzo_id not found in queue or history"
        )

    def remove(self, nzo_id: str, *, delete_files: bool = True) -> None:
        params = {
            "mode": "queue_delete" if delete_files else "queue",
            "value": nzo_id,
            "apikey": self._api_key,
            "output": "json",
        }
        try:
            response = self._client.get(f"{self.base_url}/api", params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DownloadClientError(f"SABnzbd delete request failed: {exc}") from exc
