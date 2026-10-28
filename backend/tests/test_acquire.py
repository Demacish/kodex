"""Acquisition (kodex.acquire), phase 6's gate: a missing issue is
requested, approved, and then, with no one doing anything more, found in
Prowlarr, downloaded by qBittorrent, imported into its series' folder,
scanned, and the request fulfilled. Prowlarr and qBittorrent are fakes
answering the calls their APIs document."""

from __future__ import annotations

import zipfile
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select

from app.config import get_settings
from app.models.book import Book
from app.models.download import Download
from app.models.enums import DownloadStatus, LibraryType, RequestStatus
from app.models.library import Library
from app.models.request import Request
from app.models.series import Series
from app.workers.tasks import scan_library_task
from kodex.acquire import pipeline
from kodex.acquire.clients.prowlarr import ProwlarrResult


def _cbz(path: Path, number: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for page in range(2):
            zf.writestr(f"{page:03d}.jpg", f"Stjärnhavet {number}, page {page}".encode())


def _result(
    title: str, protocol: str = "torrent", url: str = "magnet:?xt=urn:btih:abcdef0123456789&dn=x"
) -> ProwlarrResult:
    return ProwlarrResult(title=title, download_url=url, protocol=protocol, indexer="fake", size=1, publish_date=None)


@pytest.fixture
def settings(monkeypatch, tmp_path):
    def apply(**values: object) -> None:
        for name, value in values.items():
            monkeypatch.setenv(name.upper(), str(value))
        get_settings.cache_clear()

    apply(libraries_root=tmp_path / "libraries", downloads_staging_dir=tmp_path / "downloads", acquire_enabled="false",
          prowlarr_url="http://prowlarr.test", prowlarr_api_key="k", qbittorrent_url="http://qbt.test",
          qbittorrent_username="kodex", qbittorrent_password="hemligt", sabnzbd_url="")  # fmt: skip
    yield apply
    get_settings.cache_clear()


def test_a_result_is_the_issue_only_with_its_series_and_number(settings):
    choose = pipeline.score
    assert choose(_result("Stjärnhavet 002 (2021) (Digital)"), "Stjärnhavet", 2.0)
    assert choose(_result("Stjarnhavet #2"), "Stjärnhavet", 2.0)  # without the diacritic
    assert choose(_result("Stjärnhavet v02"), "Stjärnhavet", 2.0)
    assert choose(_result("Stjärnhavet 2.5"), "Stjärnhavet", 2.5)
    assert choose(_result("Stjärnhavet 003 (2002)"), "Stjärnhavet", 2.0) is None  # 2002 is a year
    assert choose(_result("Stjärnhavet 001-012 (2021)"), "Stjärnhavet", 2.0) is None  # a pack
    assert choose(_result("Stjärnhavet 012 (2019-2020)"), "Stjärnhavet", 12.0)  # years aren't a pack
    assert choose(_result("Månskeppet 002"), "Stjärnhavet", 2.0) is None


def test_the_best_result_is_one_a_client_can_take(settings):
    usenet = _result("Stjärnhavet 002 (Digital)", protocol="usenet", url="http://nzb.test/2")
    torrent_file = _result("Stjärnhavet 002", url="http://indexer.test/2.torrent")  # not a magnet link
    magnet = _result("Stjärnhavet 002 (2021)")
    choice = pipeline.choose([usenet, torrent_file, magnet], "Stjärnhavet", 2.0)
    assert choice is not None and choice.result is magnet  # no SABnzbd here, and qBittorrent takes magnets


def test_off_by_default(settings, api):
    client, _ = api
    assert pipeline.enabled() is False
    assert client.get("/api/acquire").json() == {"enabled": False, "clients": ["qbittorrent"]}


def test_a_missing_issue_arrives_after_approval(settings, api, tmp_path):
    client, session_factory = api
    folder = tmp_path / "libraries" / "serier" / "Stjärnhavet"
    _cbz(folder / "Stjärnhavet 001.cbz", 1)
    _cbz(folder / "Stjärnhavet 003.cbz", 3)
    with session_factory() as db:
        library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS, grouping_strategy="folder")
        db.add(library)
        db.commit()
        library_id = library.id
    scan_library_task(library_id)
    with session_factory() as db:
        series = db.scalars(select(Series).where(Series.library_id == library_id)).one()
        series_id = series.id
        assert sorted(b.number for b in db.scalars(select(Book).where(Book.series_id == series_id))) == [1.0, 3.0]

    asked = client.post("/api/requests", json={"media_type": "series", "series_id": series_id, "issue_number": 2})
    assert asked.status_code == 201, asked.text
    request = asked.json()
    assert (request["title"], request["status"]) == ("Stjärnhavet #2", "pending")

    settings(acquire_enabled="true")
    staging = tmp_path / "downloads"
    content = staging / "Stjärnhavet 002 (2021) (Digital)"
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://prowlarr.test/api/v1/search").respond(json=[
            {"title": "Stjärnhavet 001-012 (2021)", "magnetUrl": "magnet:?xt=urn:btih:ffff", "protocol": "torrent", "indexer": "x"},
            {"title": "Månskeppet 002", "magnetUrl": "magnet:?xt=urn:btih:eeee", "protocol": "torrent", "indexer": "x"},
            {"title": "Stjärnhavet 002 (2021) (Digital)", "magnetUrl": "magnet:?xt=urn:btih:abcdef0123456789",
             "protocol": "torrent", "indexer": "x", "size": 12345},
        ])  # fmt: skip
        login = mock.post("http://qbt.test/api/v2/auth/login").respond(text="Ok.")
        added = mock.post("http://qbt.test/api/v2/torrents/add").respond(text="Ok.")
        info = mock.get("http://qbt.test/api/v2/torrents/info")
        info.side_effect = [
            httpx.Response(200, json=[{"state": "downloading", "progress": 0.4}]),
            httpx.Response(200, json=[{"state": "uploading", "progress": 1.0, "save_path": str(staging),
                                       "content_path": str(content)}]),
        ]  # fmt: skip

        approved = client.put(f"/api/requests/{request['id']}", json={"status": "approved"})
        assert approved.status_code == 200
        # The worker runs what approving queued:
        assert pipeline.acquire_request_task(request["id"])["status"] == "downloading"
        assert login.called and b"abcdef0123456789" in added.calls.last.request.content

        with session_factory() as db:
            assert pipeline.poll(db) == 0  # still downloading
        _cbz(content / "Stjärnhavet 002.cbz", 2)
        (content / "info.nfo").write_text("not a comic")
        with session_factory() as db:
            assert pipeline.poll(db) == 1

    assert (folder / "Stjärnhavet 002.cbz").is_file()
    with session_factory() as db:
        numbers = sorted(b.number for b in db.scalars(select(Book).where(Book.series_id == series_id)))
        assert numbers == [1.0, 2.0, 3.0]
        fulfilled = db.get(Request, request["id"])
        assert fulfilled is not None and fulfilled.status == RequestStatus.FULFILLED
        download = db.get(Download, fulfilled.download_id)
        assert download is not None and download.status == DownloadStatus.COMPLETED
    shown = client.get("/api/requests/mine").json()
    assert [(r["series_id"], r["issue_number"], r["download_status"]) for r in shown] == [(series_id, 2.0, "completed")]


def test_nothing_found_is_noted_for_the_admin(settings, api, tmp_path):
    client, session_factory = api
    _cbz(tmp_path / "libraries" / "serier" / "Stjärnhavet" / "Stjärnhavet 001.cbz", 1)
    with session_factory() as db:
        library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS, grouping_strategy="folder")
        db.add(library)
        db.commit()
        library_id = library.id
    scan_library_task(library_id)
    with session_factory() as db:
        series_id = db.scalars(select(Series.id).where(Series.library_id == library_id)).one()
    request = client.post(
        "/api/requests", json={"media_type": "series", "series_id": series_id, "issue_number": 7}
    ).json()
    settings(acquire_enabled="true")
    client.put(f"/api/requests/{request['id']}", json={"status": "approved"})
    with respx.mock() as mock:
        mock.get("http://prowlarr.test/api/v1/search").respond(json=[])
        assert pipeline.acquire_request_task(request["id"])["status"] == "no_match"
    with session_factory() as db:
        noted = db.get(Request, request["id"])
        assert (
            noted is not None and noted.status == RequestStatus.APPROVED and "Stjärnhavet 7" in (noted.admin_note or "")
        )


def test_a_request_needs_both_series_and_number(settings, api):
    client, _ = api
    assert client.post("/api/requests", json={"media_type": "series", "series_id": 1}).status_code == 422
    assert client.post("/api/requests", json={"media_type": "series", "title": " "}).status_code == 422
