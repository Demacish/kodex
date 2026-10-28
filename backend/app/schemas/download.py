from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.enums import DownloadClientType, DownloadSource, DownloadStatus


class DownloadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: int | None
    source: DownloadSource
    client: DownloadClientType
    external_id: str | None
    title: str
    status: DownloadStatus
    progress: float | None
    save_path: str | None
    library_id: int | None
    error_message: str | None
    created_by_user_id: int | None
    created_at: dt.datetime
    updated_at: dt.datetime


class DownloadCreateIn(BaseModel):
    """POST /downloads — starts a torrent/nzb download directly (an admin
    picking a Prowlarr/manual result). C10 only handles QBITTORRENT/
    SABNZBD here; DIRECT_HTTP downloads (Anna's Archive/GetComics, C12/
    C13) are created by their own dedicated search-result endpoints
    instead, since those already have the file in hand rather than a
    torrent/nzb link to hand off to a client.
    """

    source: DownloadSource
    client: DownloadClientType
    source_url: str
    title: str
    library_id: int
    request_id: int | None = None

    @model_validator(mode="after")
    def _check_client(self) -> DownloadCreateIn:
        if self.client not in (DownloadClientType.QBITTORRENT, DownloadClientType.SABNZBD):
            raise ValueError("POST /downloads only accepts client=qbittorrent or sabnzbd")
        return self


class ProwlarrSearchResultOut(BaseModel):
    """One normalized, non-persisted Prowlarr search hit — see
    kodex/acquire/clients/prowlarr.py. Nothing here is written to the database
    until POST /downloads/from-search is called with a chosen result.
    """

    title: str
    download_url: str
    protocol: str
    indexer: str
    size: int | None
    publish_date: str | None


class DownloadFromSearchIn(BaseModel):
    """POST /downloads/from-search — the admin picked one Prowlarr result
    to actually fetch. `protocol` (as reported by Prowlarr) picks the
    download client: torrent -> qBittorrent, usenet -> SABnzbd.
    """

    download_url: str
    protocol: str
    title: str
    library_id: int
    request_id: int | None = None

    @model_validator(mode="after")
    def _check_protocol(self) -> DownloadFromSearchIn:
        if self.protocol not in ("torrent", "usenet"):
            raise ValueError('protocol must be "torrent" or "usenet"')
        return self


class AnnasArchiveSearchResultOut(BaseModel):
    """One normalized, non-persisted Anna's Archive search hit — see
    kodex/acquire/clients/annas_archive.py. Interactive-only source: nothing is
    ever fetched automatically, this is purely for an admin to browse.
    """

    title: str
    detail_url: str
    mirror: str


class DownloadFromAnnasArchiveIn(BaseModel):
    """POST /downloads/from-annas-archive — creates a tracking-only
    Download row (status=NEEDS_REVIEW, no job enqueued) so the chosen
    result shows up in the admin downloads list as a to-do: visit
    `detail_url`, download manually, then place the file via the B7
    library-upload endpoint.
    """

    title: str
    detail_url: str
    library_id: int
    request_id: int | None = None


class GetComicsSearchResultOut(BaseModel):
    """One normalized, non-persisted GetComics search hit — see
    kodex/acquire/clients/scrapers/getcomics.py.
    """

    title: str
    download_url: str


class DownloadFromGetComicsIn(BaseModel):
    """POST /downloads/from-getcomics — creates a Download row and
    enqueues fetch_direct_http_download_task (C12), which fetches the
    file itself since there's no separate download client involved.
    """

    title: str
    download_url: str
    library_id: int
    request_id: int | None = None


class DownloadWebhookIn(BaseModel):
    """Body of POST /downloads/{id}/webhook-complete — the download
    client's completion script reports where the finished file(s) ended
    up (in ITS OWN filesystem view — see kodex/acquire/clients/manager.py's
    map_download_path for how that gets translated to Kodex's own view).
    """

    save_path: str
