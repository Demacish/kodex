"""Tests for the request system's API layer (kodex/acquire/requests.py):
submitting a request, listing your own, and the admin queue (list/update).
The `api` fixture's fixed user is an admin (see conftest.py), so these
tests use dependency overrides where a non-admin caller matters (mirroring
the pattern in test_delivery.py for a non-default user).

Notifications are exercised separately in test_notifications.py — here,
Settings has no Telegram/Discord configured (the default in this test
environment, see test_notifications.py's own default-settings test), so
create_request's best-effort notify call is a real no-op rather than
something that needs mocking.
"""

from __future__ import annotations

import kodex.acquire.requests as requests_module
from app.auth import get_current_user, require_admin
from app.config import Settings
from app.main import app
from app.models.enums import LibraryType
from app.models.library import Library
from app.models.user import User
from kodex.acquire.clients.prowlarr import ProwlarrResult


def test_create_request_and_list_mine(api):
    client, _ = api

    response = client.post(
        "/requests",
        json={"title": "Bloodborne: The Board Game", "media_type": "series", "external_link": "https://example.com"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Bloodborne: The Board Game"
    assert body["media_type"] == "series"
    assert body["status"] == "pending"
    assert body["admin_note"] is None
    assert body["requested_by_username"] == "test"

    mine = client.get("/requests/mine")
    assert mine.status_code == 200
    assert [r["title"] for r in mine.json()] == ["Bloodborne: The Board Game"]


def test_create_request_rejects_blank_title(api):
    client, _ = api
    response = client.post("/requests", json={"title": "   ", "media_type": "ebook"})
    assert response.status_code == 422


def test_create_request_rejects_unknown_media_type(api):
    client, _ = api
    response = client.post("/requests", json={"title": "X", "media_type": "movie"})
    assert response.status_code == 422


def _seed_requests(client) -> tuple[int, int]:
    first = client.post("/requests", json={"title": "First", "media_type": "manga"})
    second = client.post("/requests", json={"title": "Second", "media_type": "ebook"})
    return first.json()["id"], second.json()["id"]


def test_admin_queue_lists_all_requests_oldest_first(api):
    client, _ = api
    first_id, second_id = _seed_requests(client)

    listed = client.get("/requests")
    assert listed.status_code == 200
    assert [r["id"] for r in listed.json()] == [first_id, second_id]


def test_admin_queue_filters_by_status(api):
    client, _ = api
    first_id, second_id = _seed_requests(client)

    client.put(f"/requests/{first_id}", json={"status": "approved"})

    pending = client.get("/requests", params={"status": "pending"})
    assert [r["id"] for r in pending.json()] == [second_id]

    approved = client.get("/requests", params={"status": "approved"})
    assert [r["id"] for r in approved.json()] == [first_id]


def test_update_request_sets_status_and_admin_note(api):
    client, _ = api
    request_id, _ = _seed_requests(client)

    response = client.put(f"/requests/{request_id}", json={"status": "fulfilled", "admin_note": "Klart!"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "fulfilled"
    assert body["admin_note"] == "Klart!"


def test_update_request_404_for_unknown_id(api):
    client, _ = api
    response = client.put("/requests/999", json={"status": "approved"})
    assert response.status_code == 404


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


def test_auto_download_queues_a_download_on_a_safe_match(api, monkeypatch):
    fake_queue = _FakeQueue()
    monkeypatch.setattr(requests_module, "get_download_queue", lambda: fake_queue)
    fake_result = ProwlarrResult(
        title="Absolute Corvid 001",
        download_url="magnet:?xt=urn:btih:abc",
        protocol="torrent",
        indexer="X",
        size=123,
        publish_date=None,
    )
    monkeypatch.setattr(requests_module, "prowlarr_search", lambda query, *, base_url, api_key: [fake_result])

    client, session_factory = api
    library_id = _seed_library(session_factory)
    request_id = client.post("/requests", json={"title": "Absolute Corvid 001", "media_type": "series"}).json()["id"]

    response = client.post(f"/requests/{request_id}/auto-download", json={"library_id": library_id})

    assert response.status_code == 200
    body = response.json()
    assert body["auto_download_enabled"] is True
    assert body["download_id"] is not None
    assert body["status"] == "approved"
    assert len(fake_queue.calls) == 1


def test_auto_download_falls_back_when_no_result_is_close_enough(api, monkeypatch):
    fake_queue = _FakeQueue()
    monkeypatch.setattr(requests_module, "get_download_queue", lambda: fake_queue)
    unrelated_result = ProwlarrResult(
        title="Completely Different Comic",
        download_url="magnet:?xt=urn:btih:xyz",
        protocol="torrent",
        indexer="X",
        size=123,
        publish_date=None,
    )
    monkeypatch.setattr(requests_module, "prowlarr_search", lambda query, *, base_url, api_key: [unrelated_result])

    client, session_factory = api
    library_id = _seed_library(session_factory)
    request_id = client.post("/requests", json={"title": "Absolute Corvid 001", "media_type": "series"}).json()["id"]

    response = client.post(f"/requests/{request_id}/auto-download", json={"library_id": library_id})

    assert response.status_code == 200
    body = response.json()
    assert body["auto_download_enabled"] is True  # the attempt is still recorded
    assert body["download_id"] is None
    assert body["status"] == "pending"  # untouched — falls back to manual handling
    assert len(fake_queue.calls) == 0


def test_auto_download_falls_back_when_prowlarr_is_unreachable(api, monkeypatch):
    from kodex.acquire.clients.base import DownloadClientError

    def _raise(query, *, base_url, api_key):
        raise DownloadClientError("Prowlarr is not configured")

    monkeypatch.setattr(requests_module, "prowlarr_search", _raise)

    client, session_factory = api
    library_id = _seed_library(session_factory)
    request_id = client.post("/requests", json={"title": "X", "media_type": "series"}).json()["id"]

    response = client.post(f"/requests/{request_id}/auto-download", json={"library_id": library_id})

    assert response.status_code == 200
    assert response.json()["download_id"] is None


def test_auto_download_unknown_library_404s(api):
    client, _ = api
    request_id = client.post("/requests", json={"title": "X", "media_type": "series"}).json()["id"]

    response = client.post(f"/requests/{request_id}/auto-download", json={"library_id": 999999})
    assert response.status_code == 404


def test_auto_download_unknown_request_404s(api):
    client, session_factory = api
    library_id = _seed_library(session_factory)

    response = client.post("/requests/999999/auto-download", json={"library_id": library_id})
    assert response.status_code == 404


def test_send_to_mylar3_adds_a_safe_match(api, monkeypatch):
    from app.enrichment.base import Candidate

    monkeypatch.setattr(requests_module, "get_settings", lambda: Settings(comicvine_api_key="cvkey"))
    fake_candidate = Candidate(external_id="12345", title="Absolute Corvid", year=2024)
    monkeypatch.setattr(requests_module.comicvine, "search", lambda query, api_key, **kw: [fake_candidate])
    add_calls = []
    monkeypatch.setattr(requests_module.mylar3, "add_comic", lambda cvid, **kw: add_calls.append(cvid))

    client, _ = api
    request_id = client.post("/requests", json={"title": "Absolute Corvid", "media_type": "series"}).json()["id"]

    response = client.post(f"/requests/{request_id}/send-to-mylar3")

    assert response.status_code == 200
    assert response.json()["auto_download_enabled"] is True
    assert add_calls == ["12345"]


def test_send_to_mylar3_falls_back_when_no_match_is_close_enough(api, monkeypatch):
    from app.enrichment.base import Candidate

    monkeypatch.setattr(requests_module, "get_settings", lambda: Settings(comicvine_api_key="cvkey"))
    fake_candidate = Candidate(external_id="12345", title="Completely Different Comic", year=2024)
    monkeypatch.setattr(requests_module.comicvine, "search", lambda query, api_key, **kw: [fake_candidate])
    add_calls = []
    monkeypatch.setattr(requests_module.mylar3, "add_comic", lambda cvid, **kw: add_calls.append(cvid))

    client, _ = api
    request_id = client.post("/requests", json={"title": "Absolute Corvid", "media_type": "series"}).json()["id"]

    response = client.post(f"/requests/{request_id}/send-to-mylar3")

    assert response.status_code == 200
    assert add_calls == []


def test_send_to_mylar3_surfaces_client_error_as_502(api, monkeypatch):
    from app.enrichment.base import Candidate
    from kodex.acquire.clients.base import DownloadClientError

    monkeypatch.setattr(requests_module, "get_settings", lambda: Settings(comicvine_api_key="cvkey"))
    fake_candidate = Candidate(external_id="12345", title="Absolute Corvid", year=2024)
    monkeypatch.setattr(requests_module.comicvine, "search", lambda query, api_key, **kw: [fake_candidate])

    def _raise(cvid, **kw):
        raise DownloadClientError("Mylar3 is not configured")

    monkeypatch.setattr(requests_module.mylar3, "add_comic", _raise)

    client, _ = api
    request_id = client.post("/requests", json={"title": "Absolute Corvid", "media_type": "series"}).json()["id"]

    response = client.post(f"/requests/{request_id}/send-to-mylar3")
    assert response.status_code == 502


def test_send_to_mylar3_unknown_request_404s(api):
    client, _ = api
    response = client.post("/requests/999999/send-to-mylar3")
    assert response.status_code == 404


def test_send_to_kapowarr_adds_a_safe_match(api, monkeypatch):
    from app.enrichment.base import Candidate

    monkeypatch.setattr(requests_module, "get_settings", lambda: Settings(comicvine_api_key="cvkey"))
    fake_candidate = Candidate(external_id="67890", title="Saga", year=2012)
    monkeypatch.setattr(requests_module.comicvine, "search", lambda query, api_key, **kw: [fake_candidate])
    add_calls = []
    monkeypatch.setattr(requests_module.kapowarr, "add_volume", lambda cvid, **kw: add_calls.append(cvid))

    client, _ = api
    request_id = client.post("/requests", json={"title": "Saga", "media_type": "series"}).json()["id"]

    response = client.post(f"/requests/{request_id}/send-to-kapowarr")

    assert response.status_code == 200
    assert response.json()["auto_download_enabled"] is True
    assert add_calls == ["67890"]


def test_send_to_kapowarr_unknown_request_404s(api):
    client, _ = api
    response = client.post("/requests/999999/send-to-kapowarr")
    assert response.status_code == 404


def test_non_admin_cannot_see_or_update_the_queue(api):
    client, _ = api
    request_id, _ = _seed_requests(client)

    # The `api` fixture overrides require_admin with a blanket "it's the
    # admin fixed user" stub (see conftest.py), which would make this test
    # trivially pass without checking anything. Dropping that override and
    # only overriding get_current_user instead lets require_admin's real
    # body run — it just wraps get_current_user (Depends resolution
    # follows the override too), so this actually exercises the 403 path.
    non_admin = User(id=2, oidc_subject="other-sub", username="other", is_admin=False)
    app.dependency_overrides[get_current_user] = lambda: non_admin
    del app.dependency_overrides[require_admin]

    listed = client.get("/requests")
    updated = client.put(f"/requests/{request_id}", json={"status": "approved"})

    assert listed.status_code == 403
    assert updated.status_code == 403

    # A non-admin can still see their own requests (empty here, since the
    # earlier ones were created by the admin fixture user, not this one).
    mine = client.get("/requests/mine")
    assert mine.status_code == 200
    assert mine.json() == []
