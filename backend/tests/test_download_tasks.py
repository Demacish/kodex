"""Tests for app/workers/tasks.py's start_download_task and
import_completed_download_task (C10). Same SessionLocal-monkeypatch
convention as test_check_followed_series_task.py — these tasks open
their own DB session, so redirecting app.workers.tasks.SessionLocal to a
fixture session is how they get tested against an isolated in-memory DB.

Reading a row back *after* the task under test has run needs a fresh
session on the same engine, not the fixture session itself: the task's
own `finally: db.close()` closes that exact session object (SessionLocal
is monkeypatched to return it), so touching an attribute afterwards is
the same DetachedInstanceError trap test_check_followed_series_task.py
already documents — see _reload below.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

import app.workers.tasks as tasks
from app.models.download import Download
from app.models.enums import (
    DownloadClientType,
    DownloadSource,
    DownloadStatus,
    LibraryType,
    RequestMediaType,
    RequestStatus,
)
from app.models.library import Library
from app.models.request import Request
from app.models.user import User
from kodex.acquire.clients.base import DownloadClientError
from tests.db import fresh_engine


@pytest.fixture
def db():
    engine = fresh_engine()
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()


def _reload(db, model, row_id):
    """Returns a plain SimpleNamespace snapshot of `model`'s columns for
    `row_id`, read through a fresh session on the same engine (the
    fixture's own `db` is closed by the task under test by this point,
    same SessionLocal-monkeypatch reasoning as test_check_followed_series
    _task.py). Deliberately copies every scalar value out to a plain
    object WHILE the session is still open, rather than returning the ORM
    instance itself — closing this helper's own session expires/detaches
    it regardless of expunge(), the same DetachedInstanceError trap, just
    triggered by close()'s implicit rollback instead of an explicit
    commit.
    """
    session = sessionmaker(bind=db.get_bind(), future=True)()
    try:
        obj = session.get(model, row_id)
        if obj is None:
            return None
        columns = model.__table__.columns.keys()
        return SimpleNamespace(**{column: getattr(obj, column) for column in columns})
    finally:
        session.close()


def _fake_settings(**overrides):
    defaults = dict(
        qbittorrent_url="http://qbt",
        qbittorrent_username="a",
        qbittorrent_password="b",
        sabnzbd_url="http://sab",
        sabnzbd_api_key="key",
        libraries_root=None,
        download_path_map_torrent="",
        download_path_map_usenet="",
        downloads_staging_dir="/data/downloads",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_download(
    db,
    *,
    client: DownloadClientType,
    library_id: int | None = None,
    request_id: int | None = None,
    save_path: str | None = None,
) -> int:
    download = Download(
        source=DownloadSource.PROWLARR,
        client=client,
        title="Absolute Corvid 001",
        status=DownloadStatus.QUEUED,
        library_id=library_id,
        request_id=request_id,
        save_path=save_path,
    )
    db.add(download)
    db.commit()
    return download.id


def test_start_download_task_qbittorrent_success(db, monkeypatch):
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(tasks, "get_settings", lambda: _fake_settings())
    monkeypatch.setattr(tasks.QBittorrentClient, "add_magnet", lambda self, url, *, save_path: "abc123hash")
    monkeypatch.setattr(tasks.QBittorrentClient, "close", lambda self: None)

    download_id = _make_download(db, client=DownloadClientType.QBITTORRENT)

    result = tasks.start_download_task(download_id, "magnet:?xt=urn:btih:abc123hash")

    assert result == {"status": "downloading", "external_id": "abc123hash"}
    download = _reload(db, Download, download_id)
    assert download.status == DownloadStatus.DOWNLOADING
    assert download.external_id == "abc123hash"


def test_start_download_task_sabnzbd_success(db, monkeypatch):
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(tasks, "get_settings", lambda: _fake_settings())
    monkeypatch.setattr(tasks.SabnzbdClient, "add_url", lambda self, url, **kw: "SABnzbd_nzo_1")
    monkeypatch.setattr(tasks.SabnzbdClient, "close", lambda self: None)

    download_id = _make_download(db, client=DownloadClientType.SABNZBD)

    result = tasks.start_download_task(download_id, "http://indexer/x.nzb")

    assert result == {"status": "downloading", "external_id": "SABnzbd_nzo_1"}


def test_start_download_task_marks_failed_on_client_error(db, monkeypatch):
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(tasks, "get_settings", lambda: _fake_settings(qbittorrent_password="wrong"))

    def _raise(self, url, *, save_path):
        raise DownloadClientError("login rejected")

    monkeypatch.setattr(tasks.QBittorrentClient, "add_magnet", _raise)
    monkeypatch.setattr(tasks.QBittorrentClient, "close", lambda self: None)

    download_id = _make_download(db, client=DownloadClientType.QBITTORRENT)

    result = tasks.start_download_task(download_id, "magnet:?xt=urn:btih:x")

    assert result["status"] == "failed"
    download = _reload(db, Download, download_id)
    assert download.status == DownloadStatus.FAILED
    assert download.error_message == "login rejected"


class _FakeStreamResponse:
    def __init__(self, chunks: list[bytes], *, status_code: int = 200) -> None:
        self._chunks = chunks
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("boom", request=None, response=self)  # type: ignore[arg-type]

    def iter_bytes(self):
        yield from self._chunks


class _FakeStreamContext:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    def __enter__(self):
        return self._response

    def __exit__(self, *exc_info):
        return False


def test_fetch_direct_http_download_task_downloads_and_imports(db, tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(tasks, "get_scan_queue", lambda: SimpleNamespace(enqueue=lambda *a, **kw: None))
    monkeypatch.setattr(
        tasks.httpx,
        "stream",
        lambda method, url, *, timeout, follow_redirects: _FakeStreamContext(_FakeStreamResponse([b"fake bytes"])),
    )

    staging = tmp_path / "staging"
    libraries_root = tmp_path / "libraries"
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db.add(library)
    db.commit()

    monkeypatch.setattr(
        tasks, "get_settings", lambda: _fake_settings(libraries_root=libraries_root, downloads_staging_dir=staging)
    )

    download = Download(
        source=DownloadSource.PROWLARR,
        client=DownloadClientType.DIRECT_HTTP,
        title="Absolute Corvid 001",
        status=DownloadStatus.QUEUED,
        library_id=library.id,
    )
    db.add(download)
    db.commit()
    download_id = download.id

    result = tasks.fetch_direct_http_download_task(download_id, "http://cdn.example/batman-001.cbz")

    assert result["status"] == "completed"
    assert (libraries_root / "serier" / "Absolute Corvid 001.cbz").is_file()
    download = _reload(db, Download, download_id)
    assert download.status == DownloadStatus.COMPLETED


def test_fetch_direct_http_download_task_marks_failed_on_http_error(db, tmp_path, monkeypatch):
    import httpx

    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)

    def _raise_stream(method, url, *, timeout, follow_redirects):
        raise httpx.ConnectError("down", request=None)

    monkeypatch.setattr(tasks.httpx, "stream", _raise_stream)
    monkeypatch.setattr(tasks, "get_settings", lambda: _fake_settings(downloads_staging_dir=tmp_path / "staging"))

    download_id = _make_download(db, client=DownloadClientType.DIRECT_HTTP)

    result = tasks.fetch_direct_http_download_task(download_id, "http://cdn.example/x.cbz")

    assert result["status"] == "failed"
    download = _reload(db, Download, download_id)
    assert download.status == DownloadStatus.FAILED


def test_import_completed_download_task_moves_files_and_triggers_scan(db, tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)

    class _FakeQueue:
        def __init__(self):
            self.calls = []

        def enqueue(self, func, *args, **kwargs):
            self.calls.append((func, args))

    fake_queue = _FakeQueue()
    monkeypatch.setattr(tasks, "get_scan_queue", lambda: fake_queue)

    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "Absolute Corvid 001.cbz").write_bytes(b"fake")
    (staging / "sample.nfo").write_text("junk")  # not importable — must be left behind

    libraries_root = tmp_path / "libraries"
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db.add(library)
    db.commit()

    monkeypatch.setattr(tasks, "get_settings", lambda: _fake_settings(libraries_root=libraries_root))

    download_id = _make_download(
        db, client=DownloadClientType.QBITTORRENT, library_id=library.id, save_path=str(staging)
    )

    result = tasks.import_completed_download_task(download_id)

    assert result["status"] == "completed"
    assert result["files_moved"] == 1
    assert (libraries_root / "serier" / "Absolute Corvid 001.cbz").is_file()
    assert not (staging / "Absolute Corvid 001.cbz").exists()  # moved, not copied
    assert (staging / "sample.nfo").exists()  # left behind — not an importable extension
    assert len(fake_queue.calls) == 1

    download = _reload(db, Download, download_id)
    assert download.status == DownloadStatus.COMPLETED


def test_import_completed_download_task_fulfills_linked_request(db, tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(tasks, "get_scan_queue", lambda: SimpleNamespace(enqueue=lambda *a, **kw: None))

    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "1.epub").write_bytes(b"fake")
    libraries_root = tmp_path / "libraries"

    library = Library(name="E-böcker", path="ebooks", library_type=LibraryType.EBOOKS)
    requester = User(oidc_subject="requester", username="requester")
    db.add_all([library, requester])
    db.flush()
    user_request = Request(
        requested_by_user_id=requester.id,
        title="Some Book",
        media_type=RequestMediaType.EBOOK,
        status=RequestStatus.APPROVED,
    )
    db.add(user_request)
    db.commit()
    request_id = user_request.id  # captured before the task's own commits expire this object

    monkeypatch.setattr(tasks, "get_settings", lambda: _fake_settings(libraries_root=libraries_root))

    download_id = _make_download(
        db, client=DownloadClientType.SABNZBD, library_id=library.id, request_id=request_id, save_path=str(staging)
    )

    tasks.import_completed_download_task(download_id)

    # A raw scalar column query rather than _reload/session.get(Request, ...)
    # — fetching a full Request entity here reproducibly left it detached-
    # and-expired even immediately after session.get() returned it (not
    # fully root-caused — reading just the one column needed sidesteps it
    # entirely rather than a full entity load).
    session = sessionmaker(bind=db.get_bind(), future=True)()
    try:
        status = session.query(Request.status).filter(Request.id == request_id).scalar()
    finally:
        session.close()
    assert status == RequestStatus.FULFILLED


def test_import_completed_download_task_fails_when_no_importable_files(db, tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)

    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "readme.txt").write_text("nothing importable here")

    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db.add(library)
    db.commit()

    monkeypatch.setattr(tasks, "get_settings", lambda: _fake_settings(libraries_root=tmp_path / "libraries"))

    download_id = _make_download(
        db, client=DownloadClientType.QBITTORRENT, library_id=library.id, save_path=str(staging)
    )

    result = tasks.import_completed_download_task(download_id)

    assert result["status"] == "failed"
    assert _reload(db, Download, download_id).status == DownloadStatus.FAILED


def test_import_completed_download_task_fails_without_library_or_save_path(db, monkeypatch):
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)
    download_id = _make_download(db, client=DownloadClientType.QBITTORRENT, library_id=None, save_path=None)

    result = tasks.import_completed_download_task(download_id)

    assert result["status"] == "failed"
