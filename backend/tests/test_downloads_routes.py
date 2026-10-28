"""API-level tests for /downloads* (C10) — GET/POST/DELETE + the
webhook-complete callback. Uses the shared `api` fixture; the actual
qBittorrent/SABnzbd HTTP calls (start_download_task) and the file-move
logic (import_completed_download_task) are monkeypatched at the RQ
enqueue boundary — this file only exercises route-level behavior, see
test_download_tasks.py for the job bodies themselves.
"""

from __future__ import annotations

import kodex.acquire.downloads as downloads_module
from app.auth import get_current_user, require_admin
from app.config import Settings
from app.main import app
from app.models.download import Download
from app.models.enums import DownloadClientType, DownloadSource, DownloadStatus, LibraryType
from app.models.library import Library
from app.models.user import User
from kodex.acquire.clients.annas_archive import AnnasArchiveResult
from kodex.acquire.clients.base import DownloadClientError
from kodex.acquire.clients.prowlarr import ProwlarrResult
from kodex.acquire.clients.scrapers.getcomics import GetComicsResult


class _FakeJob:
    id = "download-job-id"


class _FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, func, *args, **kwargs):
        self.calls.append((func, args))
        return _FakeJob()


def _seed_library(session_factory) -> int:
    db = session_factory()
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db.add(library)
    db.commit()
    library_id = library.id
    db.close()
    return library_id


def test_create_download_enqueues_start_task(api, monkeypatch):
    fake_queue = _FakeQueue()
    monkeypatch.setattr(downloads_module, "get_download_queue", lambda: fake_queue)
    client, session_factory = api
    library_id = _seed_library(session_factory)

    response = client.post(
        "/downloads",
        json={
            "source": "prowlarr",
            "client": "qbittorrent",
            "source_url": "magnet:?xt=urn:btih:abc",
            "title": "Absolute Corvid 001",
            "library_id": library_id,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "queued"
    assert len(fake_queue.calls) == 1


def test_create_download_rejects_direct_http_client(api):
    client, session_factory = api
    library_id = _seed_library(session_factory)

    response = client.post(
        "/downloads",
        json={
            "source": "manual",
            "client": "direct_http",
            "source_url": "http://x/file.cbz",
            "title": "X",
            "library_id": library_id,
        },
    )
    assert response.status_code == 422  # pydantic validator rejects it


def test_create_download_unknown_library_404s(api):
    client, _ = api
    response = client.post(
        "/downloads",
        json={
            "source": "prowlarr",
            "client": "qbittorrent",
            "source_url": "magnet:?xt=urn:btih:abc",
            "title": "X",
            "library_id": 999999,
        },
    )
    assert response.status_code == 404


def test_list_downloads_filters_by_status(api):
    client, session_factory = api
    library_id = _seed_library(session_factory)
    db = session_factory()
    db.add(
        Download(
            source=DownloadSource.PROWLARR,
            client=DownloadClientType.QBITTORRENT,
            title="A",
            library_id=library_id,
            status=DownloadStatus.COMPLETED,
        )
    )
    db.add(
        Download(
            source=DownloadSource.PROWLARR,
            client=DownloadClientType.SABNZBD,
            title="B",
            library_id=library_id,
            status=DownloadStatus.QUEUED,
        )
    )
    db.commit()
    db.close()

    completed = client.get("/downloads", params={"status": "completed"}).json()
    assert len(completed) == 1
    assert completed[0]["title"] == "A"

    all_downloads = client.get("/downloads").json()
    assert len(all_downloads) == 2


def test_get_download_404s_for_unknown_id(api):
    client, _ = api
    assert client.get("/downloads/999999").status_code == 404


def test_delete_download_removes_row(api):
    client, session_factory = api
    library_id = _seed_library(session_factory)
    db = session_factory()
    download = Download(
        source=DownloadSource.MANUAL, client=DownloadClientType.QBITTORRENT, title="X", library_id=library_id
    )
    db.add(download)
    db.commit()
    download_id = download.id
    db.close()

    response = client.delete(f"/downloads/{download_id}")
    assert response.status_code == 204
    assert client.get(f"/downloads/{download_id}").status_code == 404


def test_search_downloads_proxies_prowlarr_results(api, monkeypatch):
    fake_result = ProwlarrResult(
        title="Absolute Corvid 001",
        download_url="magnet:?xt=urn:btih:abc",
        protocol="torrent",
        indexer="X",
        size=123,
        publish_date="2026-01-01",
    )
    monkeypatch.setattr(downloads_module, "prowlarr_search", lambda query, *, base_url, api_key: [fake_result])
    client, _ = api

    response = client.get("/downloads/search", params={"query": "Absolute Corvid"})

    assert response.status_code == 200
    assert response.json() == [
        {
            "title": "Absolute Corvid 001",
            "download_url": "magnet:?xt=urn:btih:abc",
            "protocol": "torrent",
            "indexer": "X",
            "size": 123,
            "publish_date": "2026-01-01",
        }
    ]


def test_search_downloads_surfaces_client_error_as_502(api, monkeypatch):
    def _raise(query, *, base_url, api_key):
        raise DownloadClientError("Prowlarr is not configured")

    monkeypatch.setattr(downloads_module, "prowlarr_search", _raise)
    client, _ = api

    response = client.get("/downloads/search", params={"query": "x"})
    assert response.status_code == 502


def test_create_download_from_search_maps_protocol_to_client(api, monkeypatch):
    fake_queue = _FakeQueue()
    monkeypatch.setattr(downloads_module, "get_download_queue", lambda: fake_queue)
    client, session_factory = api
    library_id = _seed_library(session_factory)

    response = client.post(
        "/downloads/from-search",
        json={
            "download_url": "http://sab/x.nzb",
            "protocol": "usenet",
            "title": "Absolute Corvid 002",
            "library_id": library_id,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["client"] == "sabnzbd"
    assert body["source"] == "prowlarr"
    assert len(fake_queue.calls) == 1


def test_create_download_from_search_rejects_unknown_protocol(api):
    client, session_factory = api
    library_id = _seed_library(session_factory)

    response = client.post(
        "/downloads/from-search",
        json={"download_url": "http://x", "protocol": "ftp", "title": "X", "library_id": library_id},
    )
    assert response.status_code == 422


def test_create_download_from_search_unknown_library_404s(api):
    client, _ = api
    response = client.post(
        "/downloads/from-search",
        json={"download_url": "magnet:?xt=urn:btih:abc", "protocol": "torrent", "title": "X", "library_id": 999999},
    )
    assert response.status_code == 404


def test_search_annas_archive_proxies_results(api, monkeypatch):
    fake_result = AnnasArchiveResult(
        title="Absolute Corvid Vol 1", detail_url="http://mirror/md5/abc", mirror="http://mirror"
    )
    monkeypatch.setattr(downloads_module, "annas_archive_search", lambda query, *, mirrors: [fake_result])
    client, _ = api

    response = client.get("/downloads/search-annas-archive", params={"query": "Absolute Corvid"})

    assert response.status_code == 200
    assert response.json() == [
        {"title": "Absolute Corvid Vol 1", "detail_url": "http://mirror/md5/abc", "mirror": "http://mirror"}
    ]


def test_search_annas_archive_surfaces_client_error_as_502(api, monkeypatch):
    def _raise(query, *, mirrors):
        raise DownloadClientError("no mirrors configured")

    monkeypatch.setattr(downloads_module, "annas_archive_search", _raise)
    client, _ = api

    response = client.get("/downloads/search-annas-archive", params={"query": "x"})
    assert response.status_code == 502


def test_create_download_from_annas_archive_creates_needs_review_row(api):
    client, session_factory = api
    library_id = _seed_library(session_factory)

    response = client.post(
        "/downloads/from-annas-archive",
        json={"title": "Absolute Corvid Vol 1", "detail_url": "http://mirror/md5/abc", "library_id": library_id},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "needs_review"
    assert body["client"] == "direct_http"
    assert body["source"] == "annas_archive"
    assert "http://mirror/md5/abc" in body["error_message"]


def test_create_download_from_annas_archive_unknown_library_404s(api):
    client, _ = api
    response = client.post(
        "/downloads/from-annas-archive",
        json={"title": "X", "detail_url": "http://mirror/md5/abc", "library_id": 999999},
    )
    assert response.status_code == 404


def test_search_getcomics_proxies_results(api, monkeypatch):
    fake_result = GetComicsResult(title="Absolute Corvid 001 (2026)", download_url="http://cdn.example/batman-001.cbz")
    monkeypatch.setattr(downloads_module, "getcomics_search", lambda query, *, flaresolverr_url: [fake_result])
    client, _ = api

    response = client.get("/downloads/search-getcomics", params={"query": "Absolute Corvid"})

    assert response.status_code == 200
    assert response.json() == [
        {"title": "Absolute Corvid 001 (2026)", "download_url": "http://cdn.example/batman-001.cbz"}
    ]


def test_search_getcomics_surfaces_client_error_as_502(api, monkeypatch):
    def _raise(query, *, flaresolverr_url):
        raise DownloadClientError("circuit open")

    monkeypatch.setattr(downloads_module, "getcomics_search", _raise)
    client, _ = api

    response = client.get("/downloads/search-getcomics", params={"query": "x"})
    assert response.status_code == 502


def test_create_download_from_getcomics_enqueues_fetch_task(api, monkeypatch):
    fake_queue = _FakeQueue()
    monkeypatch.setattr(downloads_module, "get_download_queue", lambda: fake_queue)
    client, session_factory = api
    library_id = _seed_library(session_factory)

    response = client.post(
        "/downloads/from-getcomics",
        json={
            "title": "Absolute Corvid 001",
            "download_url": "http://cdn.example/batman-001.cbz",
            "library_id": library_id,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["client"] == "direct_http"
    assert body["source"] == "getcomics"
    assert body["status"] == "queued"
    assert len(fake_queue.calls) == 1


def test_create_download_from_getcomics_unknown_library_404s(api):
    client, _ = api
    response = client.post(
        "/downloads/from-getcomics",
        json={"title": "X", "download_url": "http://cdn.example/x.cbz", "library_id": 999999},
    )
    assert response.status_code == 404


def test_downloads_require_admin(api):
    client, session_factory = api
    library_id = _seed_library(session_factory)

    non_admin = User(id=2, oidc_subject="non-admin-sub", username="reader", is_admin=False)
    app.dependency_overrides[get_current_user] = lambda: non_admin
    del app.dependency_overrides[require_admin]

    assert client.get("/downloads").status_code == 403
    assert (
        client.post(
            "/downloads",
            json={
                "source": "manual",
                "client": "qbittorrent",
                "source_url": "x",
                "title": "x",
                "library_id": library_id,
            },
        ).status_code
        == 403
    )


def test_webhook_complete_requires_valid_token(api, monkeypatch):
    monkeypatch.setattr(
        downloads_module,
        "get_settings",
        lambda: Settings(database_url="sqlite:///:memory:", download_webhook_secret="the-secret"),
    )
    client, session_factory = api
    library_id = _seed_library(session_factory)
    db = session_factory()
    download = Download(
        source=DownloadSource.PROWLARR, client=DownloadClientType.QBITTORRENT, title="X", library_id=library_id
    )
    db.add(download)
    db.commit()
    download_id = download.id
    db.close()

    wrong_token = client.post(
        f"/downloads/{download_id}/webhook-complete", params={"token": "wrong"}, json={"save_path": "/x"}
    )
    assert wrong_token.status_code == 403


def test_webhook_complete_rejects_when_secret_not_configured(api, monkeypatch):
    monkeypatch.setattr(
        downloads_module,
        "get_settings",
        lambda: Settings(database_url="sqlite:///:memory:", download_webhook_secret=""),
    )
    client, session_factory = api
    library_id = _seed_library(session_factory)
    db = session_factory()
    download = Download(
        source=DownloadSource.PROWLARR, client=DownloadClientType.QBITTORRENT, title="X", library_id=library_id
    )
    db.add(download)
    db.commit()
    download_id = download.id
    db.close()

    response = client.post(
        f"/downloads/{download_id}/webhook-complete", params={"token": "anything"}, json={"save_path": "/x"}
    )
    assert response.status_code == 403


def test_webhook_complete_enqueues_import_task_on_valid_token(api, monkeypatch):
    monkeypatch.setattr(
        downloads_module,
        "get_settings",
        lambda: Settings(database_url="sqlite:///:memory:", download_webhook_secret="the-secret"),
    )
    fake_queue = _FakeQueue()
    monkeypatch.setattr(downloads_module, "get_download_queue", lambda: fake_queue)

    client, session_factory = api
    library_id = _seed_library(session_factory)
    db = session_factory()
    download = Download(
        source=DownloadSource.PROWLARR, client=DownloadClientType.QBITTORRENT, title="X", library_id=library_id
    )
    db.add(download)
    db.commit()
    download_id = download.id
    db.close()

    response = client.post(
        f"/downloads/{download_id}/webhook-complete",
        params={"token": "the-secret"},
        json={"save_path": "/downloads/complete/x"},
    )

    assert response.status_code == 200
    assert response.json()["save_path"] == "/downloads/complete/x"
    assert len(fake_queue.calls) == 1


def test_webhook_complete_unknown_download_404s(api, monkeypatch):
    monkeypatch.setattr(
        downloads_module,
        "get_settings",
        lambda: Settings(database_url="sqlite:///:memory:", download_webhook_secret="the-secret"),
    )
    client, _ = api
    response = client.post(
        "/downloads/999999/webhook-complete", params={"token": "the-secret"}, json={"save_path": "/x"}
    )
    assert response.status_code == 404
