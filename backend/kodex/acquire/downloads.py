"""Batch C (C10) — tracked torrent/nzb/direct-file downloads. See
kodex/acquire/clients/ for the qBittorrent/SABnzbd clients and app/workers/
tasks.py for start_download_task/import_completed_download_task.

Code/schema only in this pass — no qBittorrent/SABnzbd/Prowlarr container
runs anywhere reachable from this deployment yet (see
claude/omnibus-och-ai-forbattringar.md). Every endpoint here still works
correctly once QBITTORRENT_URL/SABNZBD_URL etc. point at a real instance
somewhere — nothing assumes local/same-host.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.config import get_settings
from app.database import get_db
from app.models.download import Download
from app.models.enums import DownloadClientType, DownloadSource, DownloadStatus
from app.models.library import Library
from app.models.user import User
from app.schemas.download import (
    AnnasArchiveSearchResultOut,
    DownloadCreateIn,
    DownloadFromAnnasArchiveIn,
    DownloadFromGetComicsIn,
    DownloadFromSearchIn,
    DownloadOut,
    DownloadWebhookIn,
    GetComicsSearchResultOut,
    ProwlarrSearchResultOut,
)
from app.workers.queue import get_download_queue
from app.workers.tasks import fetch_direct_http_download_task, import_completed_download_task, start_download_task
from kodex.acquire.clients.annas_archive import AnnasArchiveResult, parse_mirrors
from kodex.acquire.clients.annas_archive import search as annas_archive_search
from kodex.acquire.clients.base import DownloadClientError
from kodex.acquire.clients.prowlarr import PROTOCOL_TO_CLIENT, ProwlarrResult
from kodex.acquire.clients.prowlarr import search as prowlarr_search
from kodex.acquire.clients.scrapers.getcomics import GetComicsResult
from kodex.acquire.clients.scrapers.getcomics import search as getcomics_search

router = APIRouter(prefix="/downloads", tags=["downloads"])


def _get_download_or_404(download_id: int, db: Session) -> Download:
    download = db.get(Download, download_id)
    if download is None:
        raise HTTPException(status_code=404, detail="Download not found")
    return download


@router.get("", response_model=list[DownloadOut])
def list_downloads(
    status: DownloadStatus | None = None, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> list[Download]:
    query = db.query(Download).order_by(Download.created_at.desc())
    if status is not None:
        query = query.filter(Download.status == status)
    return query.all()


@router.get("/search", response_model=list[ProwlarrSearchResultOut])
def search_downloads(query: str, _admin: User = Depends(require_admin)) -> list[ProwlarrResult]:
    """Proxies a Prowlarr search — results aren't persisted here, only
    returned for the admin to pick from via POST /downloads/from-search.
    """
    settings = get_settings()
    try:
        return prowlarr_search(query, base_url=settings.prowlarr_url, api_key=settings.prowlarr_api_key)
    except DownloadClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/from-search", response_model=DownloadOut, status_code=201)
def create_download_from_search(
    payload: DownloadFromSearchIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> Download:
    """Bridges a chosen Prowlarr search result into C10's existing
    download pipeline — same Download row + start_download_task enqueue
    as POST /downloads, just with the client derived from the result's
    protocol instead of picked explicitly.
    """
    library = db.get(Library, payload.library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    download = Download(
        request_id=payload.request_id,
        source=DownloadSource.PROWLARR,
        client=PROTOCOL_TO_CLIENT[payload.protocol],
        title=payload.title,
        library_id=payload.library_id,
        created_by_user_id=admin.id,
        status=DownloadStatus.QUEUED,
    )
    db.add(download)
    db.commit()
    db.refresh(download)

    get_download_queue().enqueue(start_download_task, download.id, payload.download_url, job_timeout="10m")
    return download


@router.get("/search-annas-archive", response_model=list[AnnasArchiveSearchResultOut])
def search_annas_archive(query: str, _admin: User = Depends(require_admin)) -> list[AnnasArchiveResult]:
    """Proxies an Anna's Archive search — same non-persisted-results shape
    as GET /downloads/search. See kodex/acquire/clients/annas_archive.py: this
    source is interactive-only, so results only ever lead to POST
    /downloads/from-annas-archive's manual-review tracking row, never an
    automatic fetch.
    """
    settings = get_settings()
    try:
        return annas_archive_search(query, mirrors=parse_mirrors(settings.annas_archive_mirrors))
    except DownloadClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/from-annas-archive", response_model=DownloadOut, status_code=201)
def create_download_from_annas_archive(
    payload: DownloadFromAnnasArchiveIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> Download:
    """Creates a NEEDS_REVIEW tracking row for a chosen Anna's Archive
    result — deliberately does NOT enqueue start_download_task (there's
    no download client to hand the link to): the admin visits
    `detail_url`, fetches the file by hand, then places it via the B7
    library-upload endpoint. This row just keeps the to-do visible in the
    admin downloads list instead of getting lost in a browser tab.
    """
    library = db.get(Library, payload.library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    download = Download(
        request_id=payload.request_id,
        source=DownloadSource.ANNAS_ARCHIVE,
        client=DownloadClientType.DIRECT_HTTP,
        title=payload.title,
        library_id=payload.library_id,
        created_by_user_id=admin.id,
        status=DownloadStatus.NEEDS_REVIEW,
        error_message=f"Interaktiv källa — hämta filen manuellt via {payload.detail_url} och ladda upp den i biblioteket.",
    )
    db.add(download)
    db.commit()
    db.refresh(download)
    return download


@router.get("/search-getcomics", response_model=list[GetComicsSearchResultOut])
def search_getcomics(query: str, _admin: User = Depends(require_admin)) -> list[GetComicsResult]:
    """Proxies a GetComics search via FlareSolverr — same non-persisted-
    results shape as GET /downloads/search, for UI reuse. See
    kodex/acquire/clients/scrapers/getcomics.py for the circuit breaker guarding
    this against a FlareSolverr instance that's down.
    """
    settings = get_settings()
    try:
        return getcomics_search(query, flaresolverr_url=settings.flaresolverr_url)
    except DownloadClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/from-getcomics", response_model=DownloadOut, status_code=201)
def create_download_from_getcomics(
    payload: DownloadFromGetComicsIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> Download:
    """Bridges a chosen GetComics result into a DIRECT_HTTP download —
    unlike POST /downloads/from-search (qBittorrent/SABnzbd), there's no
    separate download client to hand the link to, so this enqueues
    fetch_direct_http_download_task instead of start_download_task.
    """
    library = db.get(Library, payload.library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    download = Download(
        request_id=payload.request_id,
        source=DownloadSource.GETCOMICS,
        client=DownloadClientType.DIRECT_HTTP,
        title=payload.title,
        library_id=payload.library_id,
        created_by_user_id=admin.id,
        status=DownloadStatus.QUEUED,
    )
    db.add(download)
    db.commit()
    db.refresh(download)

    get_download_queue().enqueue(fetch_direct_http_download_task, download.id, payload.download_url, job_timeout="15m")
    return download


@router.get("/{download_id}", response_model=DownloadOut)
def get_download(download_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> Download:
    return _get_download_or_404(download_id, db)


@router.post("", response_model=DownloadOut, status_code=201)
def create_download(
    payload: DownloadCreateIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> Download:
    library = db.get(Library, payload.library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    download = Download(
        request_id=payload.request_id,
        source=payload.source,
        client=payload.client,
        title=payload.title,
        library_id=payload.library_id,
        created_by_user_id=admin.id,
        status=DownloadStatus.QUEUED,
    )
    db.add(download)
    db.commit()
    db.refresh(download)

    get_download_queue().enqueue(start_download_task, download.id, payload.source_url, job_timeout="10m")
    return download


@router.delete("/{download_id}", status_code=204, response_model=None)
def delete_download(download_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> None:
    """Removes Kodex's own tracking row only — deliberately does NOT also
    call the download client's own remove/cancel API (see kodex/acquire/clients/
    qbittorrent.py/sabnzbd.py's remove()): this endpoint has never been
    exercised against a real client in this deployment (see this module's
    own docstring), and a destructive remote call is exactly the kind of
    thing not to guess at working correctly. Cancelling in qBittorrent/
    SABnzbd itself is a manual step for now.
    """
    download = _get_download_or_404(download_id, db)
    db.delete(download)
    db.commit()


@router.post("/{download_id}/webhook-complete", response_model=DownloadOut)
def webhook_complete(
    download_id: int, payload: DownloadWebhookIn, token: str = Query(...), db: Session = Depends(get_db)
) -> Download:
    """Called by the download client's own completion script (qBittorrent's
    --run-on-torrent-finished / SABnzbd's completion script) — not an
    authenticated Kodex user, so gated by a shared-secret query token
    (settings.download_webhook_secret) instead of the normal OIDC session.
    An empty secret means the feature isn't configured yet — refuses
    every call rather than accepting an unauthenticated one by accident.
    """
    settings = get_settings()
    if not settings.download_webhook_secret or token != settings.download_webhook_secret:
        raise HTTPException(status_code=403, detail="Invalid or missing webhook token")

    download = _get_download_or_404(download_id, db)
    download.save_path = payload.save_path
    db.add(download)
    db.commit()
    db.refresh(download)

    get_download_queue().enqueue(import_completed_download_task, download.id, job_timeout="30m")
    return download
