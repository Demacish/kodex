"""User-submitted "please add this" requests (see the architecture plan's
"Modul: Requestsystem och notiser"). Any logged-in user can submit one and
see their own; only an admin can see the full queue and act on it. A new
request best-effort notifies you directly via Telegram/Discord (see
kodex/delivery/notify.py), but the admin queue below (GET /requests)
is always the source of truth — it doesn't depend on that notification
having actually arrived.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Protocol

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Query, Session, joinedload

from app.auth import get_current_user, require_admin, require_member
from app.config import get_settings
from app.database import get_db
from app.enrichment import comicvine
from app.enrichment.base import Candidate
from app.models.download import Download
from app.models.enums import DownloadSource, DownloadStatus, RequestStatus
from app.models.library import Library
from app.models.request import Request
from app.models.series import Series
from app.models.user import User
from app.schemas.request import RequestAutoDownloadIn, RequestCreate, RequestOut, RequestUpdate
from app.workers.queue import get_download_queue
from app.workers.tasks import start_download_task
from kodex.acquire import pipeline as acquire
from kodex.acquire.clients import kapowarr, mylar3
from kodex.acquire.clients.base import DownloadClientError
from kodex.acquire.clients.prowlarr import PROTOCOL_TO_CLIENT
from kodex.acquire.clients.prowlarr import search as prowlarr_search
from kodex.acquire.pipeline import number_label
from kodex.delivery.notify import notify_new_request

# A request's title has to be a fairly close match to a Prowlarr result's
# own title before auto-download treats it as "safe enough" to fetch
# without a human looking at it — same threshold family as C14's CSV-
# import AUTO_MATCH_THRESHOLD (0.85), just a little more lenient since a
# request title is free text a user typed, not a structured export field.
_AUTO_DOWNLOAD_MATCH_THRESHOLD = 0.72

router = APIRouter(prefix="/requests", tags=["requests"])

_MEDIA_TYPE_LABELS = {"series": "Serie", "ebook": "E-bok", "manga": "Manga"}
_STATUS_LABELS = {"pending": "Väntar", "approved": "Godkänd", "fulfilled": "Klar", "rejected": "Avvisad"}


def _to_request_out(request: Request) -> RequestOut:
    return RequestOut(
        id=request.id,
        requested_by_user_id=request.requested_by_user_id,
        requested_by_username=request.requested_by.username,
        title=request.title,
        media_type=request.media_type,
        external_link=request.external_link,
        status=request.status,
        admin_note=request.admin_note,
        created_at=request.created_at,
        updated_at=request.updated_at,
        collection_id=request.collection_id,
        collection_name=request.collection.name if request.collection else None,
        auto_download_enabled=request.auto_download_enabled,
        download_id=request.download_id,
        series_id=request.series_id,
        issue_number=request.issue_number,
        download_status=request.download.status.value if request.download else None,
    )


class _Titled(Protocol):
    @property
    def title(self) -> str: ...


def _best_title_match[T: _Titled](title: str, candidates: Sequence[T]) -> T | None:
    """Picks the single best-scoring `candidates` entry (each must have a
    plain `.title` attribute — both ProwlarrResult and enrichment's
    Candidate qualify) if it clears _AUTO_DOWNLOAD_MATCH_THRESHOLD, else
    None (falls back to manual search/matching instead). A plain
    best-score pick (not "exactly one candidate above threshold") is
    enough since the caller's own search already returns a
    relevance-ranked list. Shared by the Prowlarr, Mylar3, and Kapowarr
    auto-send flows below.
    """
    if not candidates:
        return None
    best = max(candidates, key=lambda c: SequenceMatcher(None, title.lower(), c.title.lower()).ratio())
    score = SequenceMatcher(None, title.lower(), best.title.lower()).ratio()
    return best if score >= _AUTO_DOWNLOAD_MATCH_THRESHOLD else None


def _requests_query(db: Session) -> Query[Request]:
    """_to_request_out reads request.requested_by.username and
    request.collection.name for every row — eager-loading both here
    avoids 2 extra lazy-load SELECTs per row (unbounded: grows with the
    whole request history, not just a page size) on every one of
    list_my_requests/list_requests/export_requests below. Found
    2026-09-21 in the same N+1 sweep as books.py's list_books.
    """
    return db.query(Request).options(joinedload(Request.requested_by), joinedload(Request.collection))


def _get_request_or_404(request_id: int, db: Session) -> Request:
    request = db.get(Request, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    return request


@router.post("", response_model=RequestOut, status_code=201)
def create_request(
    payload: RequestCreate, db: Session = Depends(get_db), user: User = Depends(require_member)
) -> RequestOut:
    title = payload.title.strip()
    if payload.series_id is not None:
        series = db.get(Series, payload.series_id)
        if series is None:
            raise HTTPException(status_code=404, detail="Series not found")
        title = title or f"{series.title} #{number_label(payload.issue_number or 0)}"
    request = Request(
        requested_by_user_id=user.id,
        title=title,
        media_type=payload.media_type,
        external_link=payload.external_link.strip() if payload.external_link else None,
        series_id=payload.series_id,
        issue_number=payload.issue_number,
    )
    db.add(request)
    db.commit()
    db.refresh(request)

    # Best-effort — see notify.py's docstring for why a Telegram/Discord
    # outage must never turn into a failed submission here.
    notify_new_request(request, settings=get_settings())

    return _to_request_out(request)


@router.get("/mine", response_model=list[RequestOut])
def list_my_requests(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[RequestOut]:
    requests = (
        _requests_query(db).filter(Request.requested_by_user_id == user.id).order_by(Request.created_at.desc()).all()
    )
    return [_to_request_out(r) for r in requests]


@router.get("", response_model=list[RequestOut])
def list_requests(
    status: RequestStatus | None = None, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> list[RequestOut]:
    """The admin queue — every request across every user, optionally
    filtered by status. Ordered oldest-first (unlike "mine" above, which is
    newest-first) so a pending backlog gets worked in the order it came
    in.
    """
    query = _requests_query(db)
    if status is not None:
        query = query.filter(Request.status == status)
    requests = query.order_by(Request.created_at.asc()).all()
    return [_to_request_out(r) for r in requests]


@router.get("/export")
def export_requests(
    status: RequestStatus | None = None,
    collection_id: int | None = None,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> Response:
    """CSV export of the admin queue, respecting the same filters as the
    on-screen list (status, and optionally scoped to one collection) —
    "smidigt sätt att exportera ut" a batch of requests to hand off to
    whoever actually sources comics, requested 2026-09-11 alongside the
    "Begär saknade nummer" bulk action below. BOM-prefixed UTF-8 so Excel
    renders å/ä/ö correctly, same convention narvaro's own CSV exports
    use.
    """
    query = _requests_query(db)
    if status is not None:
        query = query.filter(Request.status == status)
    if collection_id is not None:
        query = query.filter(Request.collection_id == collection_id)
    requests = query.order_by(Request.created_at.asc()).all()

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["Titel", "Typ", "Länk", "Status", "Samling", "Begärd av", "Skapad", "Anteckning"])
    for r in requests:
        writer.writerow(
            [
                r.title,
                _MEDIA_TYPE_LABELS.get(r.media_type.value, r.media_type.value),
                r.external_link or "",
                _STATUS_LABELS.get(r.status.value, r.status.value),
                r.collection.name if r.collection else "",
                r.requested_by.username,
                r.created_at.strftime("%Y-%m-%d %H:%M"),
                r.admin_note or "",
            ]
        )

    filename = f"onskemal-{collection_id or 'alla'}.csv" if collection_id else "onskemal.csv"
    return Response(
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.put("/{request_id}", response_model=RequestOut)
def update_request(
    request_id: int, payload: RequestUpdate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> RequestOut:
    request = _get_request_or_404(request_id, db)

    approved = payload.status == RequestStatus.APPROVED and request.status != RequestStatus.APPROVED
    if payload.status is not None:
        request.status = payload.status
    if payload.admin_note is not None:
        request.admin_note = payload.admin_note.strip() or None

    db.add(request)
    db.commit()
    db.refresh(request)
    # With the acquisition add-on, approving a missing issue is all it takes (kodex.acquire).
    if approved and request.series_id is not None and request.download_id is None and acquire.enabled():
        get_download_queue().enqueue(acquire.acquire_request_task, request.id, job_id=f"acquire-request-{request.id}")
    return _to_request_out(request)


@router.post("/{request_id}/auto-download", response_model=RequestOut)
def trigger_auto_download(
    request_id: int, payload: RequestAutoDownloadIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> RequestOut:
    """Batch-C tie-in (C10-C11) — opt-in, never automatic on its own. An
    admin explicitly calls this (e.g. from an "attempt automatic
    download" checkbox when approving a request) to search Prowlarr for
    the request's own title. A single safe-enough top match (see
    _best_title_match) is queued immediately, exactly like a manual
    POST /downloads/from-search pick would be, with request_id set so
    import_completed_download_task marks this Request FULFILLED once it
    lands. Anything less certain — no match, an unreachable Prowlarr, a
    lot of similarly-scored candidates — leaves the request untouched
    (still PENDING/APPROVED) for the existing manual search-and-place
    flow to handle; auto_download_enabled is still recorded either way,
    so the admin queue can show an attempt was made.
    """
    request = _get_request_or_404(request_id, db)
    library = db.get(Library, payload.library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    request.auto_download_enabled = True

    settings = get_settings()
    try:
        results = prowlarr_search(request.title, base_url=settings.prowlarr_url, api_key=settings.prowlarr_api_key)
    except DownloadClientError:
        results = []

    match = _best_title_match(request.title, results)
    if match is not None:
        download = Download(
            request_id=request.id,
            source=DownloadSource.PROWLARR,
            client=PROTOCOL_TO_CLIENT[match.protocol],
            title=match.title,
            library_id=payload.library_id,
            created_by_user_id=admin.id,
            status=DownloadStatus.QUEUED,
        )
        db.add(download)
        db.flush()
        get_download_queue().enqueue(start_download_task, download.id, match.download_url, job_timeout="10m")
        request.download_id = download.id
        request.status = RequestStatus.APPROVED

    db.add(request)
    db.commit()
    db.refresh(request)
    return _to_request_out(request)


def _best_comicvine_match(title: str) -> Candidate | None:
    settings = get_settings()
    if not settings.comicvine_api_key:
        return None
    candidates = comicvine.search(title, settings.comicvine_api_key)
    return _best_title_match(title, candidates)


@router.post("/{request_id}/send-to-mylar3", response_model=RequestOut)
def send_to_mylar3(request_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> RequestOut:
    """Requested 2026-09-21 alongside Kapowarr below — Mylar3 runs on a
    separate, user-managed host and does its own search/download/organize
    once told which Comic Vine volume to track; Kodex has no visibility
    into when a file actually lands (unlike the qBittorrent/SABnzbd
    Download-row pipeline above). The finished file arrives back into
    Kodex later via that host's own script hitting POST /libraries/{id}/
    upload (B7) — see app/config.py's upload_api_key docstring for how
    that script authenticates. No Download row here: there's nothing for
    Kodex to track. request.status is left alone (an admin marks it
    FULFILLED by hand once the file shows up) — auto_download_enabled is
    still recorded either way, matching the Prowlarr flow's own "the
    admin queue can show an attempt was made" reasoning.
    """
    request = _get_request_or_404(request_id, db)
    request.auto_download_enabled = True

    match = _best_comicvine_match(request.title)
    if match is not None:
        settings = get_settings()
        try:
            mylar3.add_comic(match.external_id, base_url=settings.mylar3_url, api_key=settings.mylar3_api_key)
        except DownloadClientError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    db.add(request)
    db.commit()
    db.refresh(request)
    return _to_request_out(request)


@router.post("/{request_id}/send-to-kapowarr", response_model=RequestOut)
def send_to_kapowarr(
    request_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> RequestOut:
    """Same shape as send_to_mylar3 above — see its own docstring."""
    request = _get_request_or_404(request_id, db)
    request.auto_download_enabled = True

    match = _best_comicvine_match(request.title)
    if match is not None:
        settings = get_settings()
        try:
            kapowarr.add_volume(
                match.external_id,
                base_url=settings.kapowarr_url,
                api_key=settings.kapowarr_api_key,
                root_folder_id=settings.kapowarr_root_folder_id,
            )
        except DownloadClientError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    db.add(request)
    db.commit()
    db.refresh(request)
    return _to_request_out(request)
