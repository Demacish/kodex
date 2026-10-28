"""Other Kodex servers: config parsing (kodex/delivery/federation), the /federation
API a server answers with, the admin view of which books another server
has, and the copy job."""

from __future__ import annotations

import zipfile
from types import SimpleNamespace

import pytest

import app.workers.tasks as tasks
import kodex.delivery.federation.admin as peer_routes
from app.models.book import Book
from app.models.enums import BookEditionType, BookFormat, LibraryType
from app.models.library import Library
from app.models.series import Series
from kodex.delivery.federation.peers import Peer, configured_peers


def test_peers_config_parsing():
    settings = SimpleNamespace(kodex_peers='[{"name": "Hemma-NAS", "url": "http://nas:20100", "upload_key": "k"}]')
    assert configured_peers(settings) == [Peer("Hemma-NAS", "http://nas:20100", "k")]
    assert configured_peers(SimpleNamespace(kodex_peers="")) == []
    assert configured_peers(SimpleNamespace(kodex_peers="not json")) == []  # logged, never raises
    assert configured_peers(SimpleNamespace(kodex_peers='[{"name": "x"}]')) == []


@pytest.fixture
def library_with_series(api):
    client, session_factory = api
    db = session_factory()
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    series = Series(library_id=library.id, title="Saga", sort_title="saga", path="Saga")
    db.add(series)
    db.flush()

    def book(number, content_hash, edition=BookEditionType.ISSUE, fmt=BookFormat.CBZ, path=None):
        b = Book(
            library_id=library.id,
            series_id=series.id,
            file_path=path or f"Saga/Saga {number:03}.cbz",
            file_format=fmt,
            file_size=1,
            file_mtime=0.0,
            number=number,
            edition_type=edition,
            content_hash=content_hash,
        )
        db.add(b)
        db.flush()
        return b.id

    ids = SimpleNamespace(
        library=library.id,
        series=series.id,
        one=book(1, "h1"),
        two=book(2, "h2"),
        vol=book(1, "hv", BookEditionType.COLLECTED, path="Saga/Saga v01.cbz"),
    )
    db.commit()
    db.close()
    return client, session_factory, ids


def test_presence_matches_same_file_or_same_volume(library_with_series):
    client, _, _ = library_with_series
    response = client.post(
        "/federation/presence",
        json={
            "books": [
                {"content_hash": "h1"},  # same file
                {"content_hash": "other", "series_title": "SAGA ", "number": 2},  # other release, same issue
                {"content_hash": "x", "series_title": "Saga", "number": 1, "edition_type": "collected"},  # same volume
                {"content_hash": "y", "series_title": "Saga", "number": 3},  # not here
                {"series_title": "Annat", "number": 1},  # other series
            ]
        },
    )
    assert response.json() == {"present": [True, True, True, False, False]}
    assert [lib["name"] for lib in client.get("/federation/libraries").json()] == ["Serier"]


def test_admin_view_of_a_series_on_other_servers(library_with_series, monkeypatch):
    client, _, ids = library_with_series

    class FakePeer:
        name = "Hemma-NAS"

        def libraries(self):
            return [{"id": 7, "name": "Serier", "library_type": "comics"}]

        def presence(self, refs):
            assert [r["content_hash"] for r in refs] == ["h1", "h2", "hv"]  # issues first, then volumes
            return [True, False, False]

    class DownPeer:
        name = "Windows"

        def libraries(self):
            raise peer_routes.PeerError("Windows: connection refused")

    monkeypatch.setattr(peer_routes, "configured_peers", lambda: [FakePeer(), DownPeer()])

    nas, down = client.get(f"/peers/series/{ids.series}").json()
    assert nas["error"] is None
    assert nas["libraries"][0]["id"] == 7
    assert [(b["book_id"], b["present"]) for b in nas["books"]] == [(ids.one, True), (ids.two, False), (ids.vol, False)]
    assert down["error"] == "Windows: connection refused"


def test_copy_endpoint_validates_server_and_books(library_with_series, monkeypatch):
    client, _, ids = library_with_series
    queued = []
    monkeypatch.setattr(peer_routes, "get_peer", lambda name: object() if name == "Hemma-NAS" else None)
    monkeypatch.setattr(
        peer_routes,
        "get_download_queue",
        lambda: SimpleNamespace(enqueue=lambda *a, **k: queued.append(a) or SimpleNamespace(id="job-1")),
    )
    assert client.post("/peers/copy", json={"peer": "Okänd", "library_id": 7, "book_ids": [ids.two]}).status_code == 404
    assert client.post("/peers/copy", json={"peer": "Hemma-NAS", "library_id": 7, "book_ids": [999]}).status_code == 404
    assert client.post("/peers/copy", json={"peer": "Hemma-NAS", "library_id": 7, "book_ids": [ids.two]}).json() == {
        "job_id": "job-1"
    }
    assert queued[0][1:] == ("Hemma-NAS", 7, [ids.two])


def test_copy_task_uploads_into_the_series_folder_and_scans_once(library_with_series, tmp_path, monkeypatch):
    _, session_factory, ids = library_with_series
    root = tmp_path / "libraries"
    (root / "serier" / "Saga").mkdir(parents=True)
    for name in ("Saga 001.cbz", "Saga 002.cbz"):
        (root / "serier" / "Saga" / name).write_bytes(b"cbz")
    folder = root / "serier" / "Saga" / "Saga v01"
    folder.mkdir()
    (folder / "001.jpg").write_bytes(b"page")
    db = session_factory()
    db.get(Book, ids.vol).file_path = "Saga/Saga v01"
    db.get(Book, ids.vol).file_format = BookFormat.IMAGE_FOLDER
    db.commit()
    db.close()

    calls = []

    class FakePeer:
        def upload(self, library_id, path, *, upload_name, subfolder, rescan):
            if upload_name.endswith(".cbz") and path.parent.name != "Saga":
                with zipfile.ZipFile(path) as zf:  # the zipped image folder
                    calls.append(("zip", zf.namelist()))
            calls.append(("upload", library_id, upload_name, subfolder, rescan))
            return "exists" if upload_name == "Saga 002.cbz" else "copied"

        def scan(self, library_id):
            calls.append(("scan", library_id))

    monkeypatch.setattr(tasks, "get_peer", lambda name: FakePeer())
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "get_settings", lambda: SimpleNamespace(libraries_root=root))

    result = tasks.copy_books_to_peer_task("Hemma-NAS", 7, [ids.one, ids.two, ids.vol])

    assert sorted(result["copied"]) == ["Saga/Saga 001.cbz", "Saga/Saga v01"]
    assert result["exists"] == ["Saga/Saga 002.cbz"]
    assert ("zip", ["001.jpg"]) in calls
    assert ("upload", 7, "Saga v01.cbz", "Saga", False) in calls
    assert all(call[4] is False for call in calls if call[0] == "upload")  # no per-file scans
    assert calls[-1] == ("scan", 7)
