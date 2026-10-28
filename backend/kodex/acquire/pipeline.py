"""A missing issue, from a request to a book in its series, with no one
doing more than approving it (the add-on, ``ACQUIRE_ENABLED``; docs/acquire.md).

1. An approved request for a series' missing number is searched for in
   Prowlarr (:func:`acquire`), as the series' title and the number.
2. The best result goes to qBittorrent (a magnet link) or SABnzbd (an NZB):
   the series' title in it, that number and not a run of numbers.
3. Every two minutes :func:`poll` asks the clients. A finished download is
   imported (:func:`import_download`): its comic and book files go into the
   series' folder, the library is scanned (which also matches the new
   book), and once the series has the number the request is fulfilled and
   the person who asked is told.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.book import Book
from app.models.download import Download
from app.models.enums import DownloadClientType, DownloadSource, DownloadStatus, RequestStatus
from app.models.library import Library
from app.models.request import Request
from app.models.series import Series
from app.models.user import User
from kodex.acquire.clients.base import DownloadClientError, DownloadClientStatus
from kodex.acquire.clients.manager import IMPORTABLE_EXTENSIONS, map_download_path
from kodex.acquire.clients.prowlarr import ProwlarrResult
from kodex.acquire.clients.prowlarr import search as prowlarr_search
from kodex.acquire.clients.qbittorrent import QBittorrentClient, extract_magnet_hash
from kodex.acquire.clients.sabnzbd import SabnzbdClient

logger = logging.getLogger(__name__)

# How alike the series' title and a result's have to be (rapidfuzz's
# partial ratio, 0–100): the result may say more ("… (2021) (Digital)").
TITLE_SIMILARITY = 85
_YEAR = re.compile(r"^(19|20)\d\d$")
_RANGE = re.compile(r"(?<!\d)(\d{1,4})\s*[-–]\s*(\d{1,4})(?!\d)")
_NUMBER = re.compile(r"(?<![\d.])(\d{1,4}(?:\.\d)?)(?![\d.])")


def enabled() -> bool:
    """The add-on is on, with Prowlarr to search and a client to download with."""
    settings = get_settings()
    has_client = bool(settings.qbittorrent_url or (settings.sabnzbd_url and settings.sabnzbd_api_key))
    return settings.acquire_enabled and bool(settings.prowlarr_url and settings.prowlarr_api_key) and has_client


def number_label(number: float) -> str:
    return str(int(number)) if number == int(number) else f"{number:g}"


def query(series: Series, number: float) -> str:
    return f"{series.title} {number_label(number)}"


def _normalized(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.casefold()).strip()


def _numbers(title: str) -> set[float]:
    found = set()
    for token in _NUMBER.findall(title):
        if _YEAR.match(token):
            continue
        found.add(float(token))
    return found


def score(result: ProwlarrResult, series_title: str, number: float) -> float | None:
    """How good a result is for the issue, or None when it isn't the issue:
    another series, another number, or a pack of several."""
    title = result.title
    similarity = fuzz.partial_ratio(_normalized(series_title), _normalized(title))
    if similarity < TITLE_SIMILARITY:
        return None
    # What the title says besides the series' name (which may have numbers of its own).
    rest = re.sub(re.escape(series_title), " ", title, count=1, flags=re.IGNORECASE)
    for low, high in _RANGE.findall(rest):
        if not (_YEAR.match(low) and _YEAR.match(high)) and float(low) != float(high):
            return None  # "001-012": a pack
    if number not in _numbers(rest):
        return None
    return float(similarity)


@dataclass
class Choice:
    result: ProwlarrResult
    client: DownloadClientType
    score: float


def _client_for(result: ProwlarrResult) -> DownloadClientType | None:
    settings = get_settings()
    if result.protocol == "torrent" and settings.qbittorrent_url and extract_magnet_hash(result.download_url):
        return DownloadClientType.QBITTORRENT
    if result.protocol == "usenet" and settings.sabnzbd_url and settings.sabnzbd_api_key:
        return DownloadClientType.SABNZBD
    return None


def choose(results: list[ProwlarrResult], series_title: str, number: float) -> Choice | None:
    ranked = []
    for result in results:
        value = score(result, series_title, number)
        client = _client_for(result)
        if value is not None and client is not None:
            ranked.append(Choice(result, client, value))
    ranked.sort(key=lambda c: (c.score, c.result.size or 0), reverse=True)
    return ranked[0] if ranked else None


def _qbittorrent() -> QBittorrentClient:
    s = get_settings()
    return QBittorrentClient(s.qbittorrent_url, s.qbittorrent_username, s.qbittorrent_password)


def _sabnzbd() -> SabnzbdClient:
    s = get_settings()
    return SabnzbdClient(s.sabnzbd_url, s.sabnzbd_api_key)


def _start(download: Download, url: str) -> str:
    if download.client == DownloadClientType.QBITTORRENT:
        qbt = _qbittorrent()
        try:
            return qbt.add_magnet(url, save_path=str(get_settings().downloads_staging_dir))
        finally:
            qbt.close()
    sab = _sabnzbd()
    try:
        return sab.add_url(url)
    finally:
        sab.close()


def _note(request: Request, text: str) -> None:
    if not request.admin_note:
        request.admin_note = text


def acquire(db: Session, request_id: int) -> dict[str, Any]:
    """Searches for an approved request's issue and starts the best download."""
    request = db.get(Request, request_id)
    if request is None or request.status != RequestStatus.APPROVED or request.download_id is not None:
        return {"status": "skipped"}
    series = db.get(Series, request.series_id) if request.series_id is not None else None
    if series is None or request.issue_number is None or not enabled():
        return {"status": "skipped"}
    settings = get_settings()
    asked = query(series, request.issue_number)
    try:
        results = prowlarr_search(asked, base_url=settings.prowlarr_url, api_key=settings.prowlarr_api_key)
    except DownloadClientError as exc:
        _note(request, f"Prowlarr: {exc}")
        db.commit()
        return {"status": "failed", "error": str(exc)}
    choice = choose(results, series.title, request.issue_number)
    if choice is None:
        _note(request, f"Inget i Prowlarr för {asked!r}")
        db.commit()
        return {"status": "no_match", "query": asked, "results": len(results)}
    download = Download(request_id=request.id, source=DownloadSource.PROWLARR, client=choice.client,
                        title=choice.result.title[:500], status=DownloadStatus.QUEUED,
                        library_id=series.library_id)  # fmt: skip
    db.add(download)
    db.flush()
    try:
        download.external_id = _start(download, choice.result.download_url)
    except DownloadClientError as exc:
        download.status = DownloadStatus.FAILED
        download.error_message = str(exc)
        request.download_id = download.id
        db.commit()
        return {"status": "failed", "error": str(exc)}
    download.status = DownloadStatus.DOWNLOADING
    request.download_id = download.id
    request.auto_download_enabled = True
    db.commit()
    return {"status": "downloading", "download_id": download.id, "title": download.title}


def _status(download: Download) -> DownloadClientStatus:
    if download.client == DownloadClientType.QBITTORRENT:
        qbt = _qbittorrent()
        try:
            return qbt.get_status(download.external_id or "")
        finally:
            qbt.close()
    sab = _sabnzbd()
    try:
        return sab.get_status(download.external_id or "")
    finally:
        sab.close()


def poll(db: Session) -> int:
    """Asks the clients about the downloads in progress; imports the finished ones. How many were imported."""
    if not enabled():
        return 0
    settings = get_settings()
    imported = 0
    running = db.scalars(
        select(Download).where(
            Download.status == DownloadStatus.DOWNLOADING,
            Download.external_id.is_not(None),
            Download.client.in_([DownloadClientType.QBITTORRENT, DownloadClientType.SABNZBD]),
        )  # fmt: skip
    ).all()
    for download in running:
        try:
            status = _status(download)
        except DownloadClientError as exc:
            logger.info("download %s: %s", download.id, exc)
            continue
        download.progress = status.progress
        if status.error and not status.is_complete:
            download.status = DownloadStatus.FAILED
            download.error_message = status.error
            db.commit()
            continue
        if not status.is_complete:
            db.commit()
            continue
        mapping = (settings.download_path_map_torrent if download.client == DownloadClientType.QBITTORRENT
                   else settings.download_path_map_usenet)  # fmt: skip
        path = status.content_path or status.save_path
        if not path:
            continue
        download.save_path = map_download_path(path, mapping)
        db.commit()
        if import_download(db, download.id).get("status") == "imported":
            imported += 1
    return imported


def _free(target: Path) -> Path:
    if not target.exists():
        return target
    for n in range(2, 100):
        candidate = target.with_name(f"{target.stem} ({n}){target.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(target)


def import_download(db: Session, download_id: int) -> dict[str, Any]:
    """Moves a finished download's files into its series' folder (or its
    library's), scans the library, and fulfils the request once the series
    has the number."""
    from app.workers.tasks import scan_library_task

    download = db.get(Download, download_id)
    if download is None or not download.save_path or download.library_id is None:
        return {"status": "skipped"}
    library = db.get(Library, download.library_id)
    request = db.get(Request, download.request_id) if download.request_id is not None else None
    series = db.get(Series, request.series_id) if request is not None and request.series_id is not None else None
    if library is None:
        download.status = DownloadStatus.FAILED
        download.error_message = "The library is gone"
        db.commit()
        return {"status": "failed"}
    source = Path(download.save_path)
    if source.is_file():
        files = [source] if source.suffix.lower() in IMPORTABLE_EXTENSIONS else []
    elif source.is_dir():
        files = sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in IMPORTABLE_EXTENSIONS)
    else:
        files = []
    if not files:
        download.status = DownloadStatus.FAILED
        download.error_message = f"No comic or book file in {source}"
        db.commit()
        return {"status": "failed", "error": download.error_message}
    target_dir = get_settings().libraries_root / library.path
    if series is not None and series.library_id == library.id and series.path:
        target_dir = target_dir / series.path
    target_dir.mkdir(parents=True, exist_ok=True)
    moved = []
    for file in files:
        target = _free(target_dir / file.name)
        shutil.move(str(file), target)
        moved.append(target.name)
    download.status = DownloadStatus.COMPLETED
    download.progress = 1.0
    db.commit()
    scan_library_task(library.id)
    db.expire_all()
    fulfilled = False
    if request is not None:
        if series is not None and request.issue_number is not None:
            fulfilled = db.scalar(select(Book.id).where(Book.series_id == series.id, Book.number == request.issue_number,
                                                        Book.missing_since.is_(None)).limit(1)) is not None  # fmt: skip
        else:
            fulfilled = True
        if fulfilled:
            request.status = RequestStatus.FULFILLED
            db.commit()
            _tell(db, request, series)
    return {"status": "imported", "files": moved, "fulfilled": fulfilled}


def _tell(db: Session, request: Request, series: Series | None) -> None:
    """The person who asked, on their ntfy topic when they have one."""
    from kodex.delivery.notify import send_ntfy

    user = db.get(User, request.requested_by_user_id)
    topic = getattr(user, "ntfy_topic", None) if user is not None else None
    if not topic:
        return
    settings = get_settings()
    click = (
        f"{settings.public_app_url.rstrip('/')}/series/{series.id}"
        if series is not None and settings.public_app_url
        else None
    )
    try:
        send_ntfy(topic, title="Önskemålet är här", message=request.title, click=click, settings=settings)
    except Exception:
        logger.warning("ntfy for request %s failed", request.id, exc_info=True)


# Job bodies (registered in kodex.jobs.registry).


def acquire_request_task(request_id: int) -> dict[str, Any]:
    from kodex.core.db import SessionLocal

    with SessionLocal() as db:
        return acquire(db, request_id)


def import_download_task(download_id: int) -> dict[str, Any]:
    from kodex.core.db import SessionLocal

    with SessionLocal() as db:
        return import_download(db, download_id)
