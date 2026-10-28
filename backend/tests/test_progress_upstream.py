"""Syncing with a central Kodex server (app/progress/upstream.py): pushes
after a save, pulls on open, and explicit resets from Kodex itself."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

import app.api.routes.reading_progress as progress_routes
import app.progress.upstream as upstream
import app.workers.tasks as tasks
from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.kosync import KosyncProgress
from app.models.library import Library
from app.models.reading_progress import ReadingProgress
from app.models.user import User
from app.progress.sync import best_position


@pytest.fixture
def server(api, monkeypatch):
    client, session_factory = api
    db = session_factory()
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    book = Book(
        library_id=library.id,
        file_path="a.cbz",
        file_format=BookFormat.CBZ,
        file_size=1,
        file_mtime=0.0,
        page_count=40,
        content_hash="hash-a",
    )
    db.add(book)
    db.commit()
    book_id = book.id
    db.close()

    pushes: list = []
    remote: dict = {}
    monkeypatch.setattr(upstream, "is_enabled", lambda settings=None: True)
    monkeypatch.setattr(upstream, "pull", lambda document: remote.get(document))
    monkeypatch.setattr(upstream, "enqueue_upstream_push", lambda *a, **k: pushes.append((a, k)))
    monkeypatch.setattr(progress_routes, "enqueue_upstream_push", lambda *a, **k: pushes.append((a, k)))
    return SimpleNamespace(client=client, factory=session_factory, book_id=book_id, pushes=pushes, remote=remote)


def _local(server):
    db = server.factory()
    try:
        row = db.query(ReadingProgress).filter(ReadingProgress.book_id == server.book_id).one()
        return row.position, row.progress_percent, row.is_finished
    finally:
        db.close()


def test_saving_progress_queues_a_push(server):
    server.client.put(f"/books/{server.book_id}/progress", json={"position": "9", "progress_percent": 25})
    assert server.pushes == [((server.book_id, 1), {"reset": False})]


def _in(seconds: int) -> int:
    return int(time.time()) + seconds


def test_opening_a_book_takes_a_newer_central_position(server):
    server.client.put(f"/books/{server.book_id}/progress", json={"position": "29", "progress_percent": 75})
    server.remote["hash-a"] = {"progress": "21", "percentage": 0.525, "device": "Kobo", "device_id": "k1",
                               "timestamp": _in(60)}  # fmt: skip

    got = server.client.get(f"/books/{server.book_id}/progress").json()

    assert (got["position"], got["locator_kind"], got["progress_percent"]) == ("20", "page", 52.5)
    assert got["device_name"] == "Kobo"


def test_opening_a_book_keeps_a_local_position_that_is_newer(server):
    server.client.put(f"/books/{server.book_id}/progress", json={"position": "9", "progress_percent": 25})
    server.remote["hash-a"] = {"progress": "21", "percentage": 0.525, "device": "Kobo", "device_id": "k1",
                               "timestamp": _in(-3600)}  # fmt: skip

    assert server.client.get(f"/books/{server.book_id}/progress").json()["position"] == "9"


def test_our_own_push_coming_back_is_left_alone(server):
    server.client.put(f"/books/{server.book_id}/progress", json={"position": "9", "progress_percent": 25})
    server.remote["hash-a"] = {"progress": "10", "percentage": 0.25, "device": "Kodex", "device_id": "kodex-server",
                               "timestamp": _in(60)}  # fmt: skip

    got = server.client.get(f"/books/{server.book_id}/progress").json()
    assert (got["position"], got["device_name"]) == ("9", None)


def test_an_unreachable_central_server_changes_nothing(server):
    server.client.put(f"/books/{server.book_id}/progress", json={"position": "9", "progress_percent": 25})
    # pull() returns None when it can't reach the server (it never raises).
    assert server.client.get(f"/books/{server.book_id}/progress").json()["position"] == "9"


def test_mark_unread_is_the_newest_position_and_pushes_a_reset(server):
    db = server.factory()
    db.add(KosyncProgress(user_id=1, document="hash-a", progress="30", percentage=0.75, device="Kobo", device_id="k1"))
    db.commit()
    db.close()

    server.client.post("/me/progress/bulk", json={"book_ids": [server.book_id], "is_finished": False})

    db = server.factory()
    user = db.get(User, 1)
    assert best_position(db, user, "hash-a").percentage == 0.0
    db.close()
    assert _local(server)[1] == 0.0
    assert server.pushes[-1] == ((server.book_id, 1), {"reset": True})


def test_reading_a_finished_book_again_is_pushed_like_any_position(server):
    server.client.put(
        f"/books/{server.book_id}/progress", json={"position": "39", "progress_percent": 100, "is_finished": True}
    )
    server.client.put(f"/books/{server.book_id}/progress", json={"position": "1", "progress_percent": 5})
    assert server.pushes[-1] == ((server.book_id, 1), {"reset": False})


def test_push_task_sends_koreader_page_numbers(server, monkeypatch):
    server.client.put(f"/books/{server.book_id}/progress", json={"position": "9", "progress_percent": 25})
    sent = []
    monkeypatch.setattr(tasks, "SessionLocal", server.factory)
    monkeypatch.setattr(tasks.upstream, "push", lambda document, **kw: sent.append((document, kw)))

    assert tasks.push_progress_upstream_task(server.book_id, 1, False) == {"pushed": True}
    assert sent == [("hash-a", {"progress": "10", "percentage": 0.25, "reset": False})]
