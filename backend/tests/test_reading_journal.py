"""The reading journal (kodex.reading.journal): every report is kept, the
newest received wins, a device's late or repeated report doesn't move the
position back, two browsers see each other's positions, positions say
what kind of locator they are, and old entries are compacted."""

from __future__ import annotations

import datetime as dt

import pytest

from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from kodex.reading import journal
from kodex.reading.models import ReadingEvent


@pytest.fixture
def book_id(api):
    _, session_factory = api
    with session_factory() as db:
        library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
        db.add(library)
        db.flush()
        book = Book(library_id=library.id, file_path="a.cbz", file_format=BookFormat.CBZ, file_size=1,
                    file_mtime=0.0, page_count=40)  # fmt: skip
        db.add(book)
        db.commit()
        return book.id


def _save(client, book_id, page, device, seq, **extra):
    body = {"position": str(page), "progress_percent": page / 40 * 100, "device_id": device,
            "device_name": f"Browser {device}", "client_seq": seq, **extra}  # fmt: skip
    response = client.put(f"/api/books/{book_id}/progress", json=body)
    assert response.status_code == 200
    return response.json()


def test_two_devices_see_each_others_position(api, book_id):
    client, _ = api
    _save(client, book_id, 5, "a", 1)
    _save(client, book_id, 9, "b", 1)
    current = client.get(f"/api/books/{book_id}/progress").json()
    assert (current["position"], current["device_id"], current["device_name"]) == ("9", "b", "Browser b")
    _save(client, book_id, 12, "a", 2)
    assert client.get(f"/api/books/{book_id}/progress").json()["position"] == "12"
    journal = client.get(f"/api/books/{book_id}/journal").json()
    assert [(e["device_id"], e["position"]) for e in journal] == [("a", "12"), ("b", "9"), ("a", "5")]


def test_a_late_report_is_kept_but_doesnt_move_back(api, book_id):
    client, _ = api
    _save(client, book_id, 20, "a", 7)
    late = _save(client, book_id, 15, "a", 6)
    assert late["position"] == "20"
    assert [e["position"] for e in client.get(f"/api/books/{book_id}/journal").json()] == ["15", "20"]


def test_a_repeated_report_is_recorded_once(api, book_id):
    client, _ = api
    _save(client, book_id, 3, "a", 1)
    _save(client, book_id, 3, "a", 1)
    assert len(client.get(f"/api/books/{book_id}/journal").json()) == 1


def test_finishing_and_restarting_are_journal_kinds(api, book_id):
    client, _ = api
    _save(client, book_id, 40, "a", 1, is_finished=True)
    _save(client, book_id, 1, "b", 1)
    kinds = [e["kind"] for e in client.get(f"/api/books/{book_id}/journal").json()]
    assert kinds == ["reset", "finished"]


def test_v1_clients_without_a_device_still_save(api, book_id):
    client, _ = api
    response = client.put(f"/api/books/{book_id}/progress", json={"position": "4", "progress_percent": 10})
    assert response.status_code == 200 and response.json()["device_id"] == "kodex"
    response = client.post("/api/me/progress/bulk", json={"book_ids": [book_id], "is_finished": True})
    assert response.status_code == 204
    assert [e["kind"] for e in client.get(f"/api/books/{book_id}/journal").json()] == ["finished", "progress"]


def test_positions_say_what_kind_they_are(api, book_id):
    client, _ = api
    saved = _save(client, book_id, 7, "a", 1, locator_kind="page")
    assert (saved["position"], saved["locator_kind"]) == ("7", "page")
    v1 = client.put(f"/api/books/{book_id}/progress", json={"position": "8", "progress_percent": 22.5}).json()
    assert v1["locator_kind"] == "page"  # inferred for v1's clients
    only = client.put(f"/api/books/{book_id}/progress", json={"position": "percent:0.5", "progress_percent": 50}).json()
    assert (only["position"], only["locator_kind"]) == (None, "percent")


def test_old_entries_are_compacted_to_one_a_day(api, book_id):
    client, session_factory = api
    for seq, page in enumerate((2, 3, 4, 40, 1, 2), start=1):
        _save(client, book_id, page, "a", seq, is_finished=page == 40)
    _save(client, book_id, 5, "a", 7)
    with session_factory() as db:
        # Everything but the last report happened 100 days ago, on one day.
        noon = (dt.datetime.now(dt.UTC) - dt.timedelta(days=100)).replace(hour=12, minute=0)
        for event in db.query(ReadingEvent).filter(ReadingEvent.client_seq < 7):
            event.received_at = noon + dt.timedelta(minutes=event.client_seq)
        db.commit()
        assert journal.compact(db, dt.datetime.now(dt.UTC) - dt.timedelta(days=90)) == 3
        db.commit()
    kept = [(e["kind"], e["position"]) for e in client.get(f"/api/books/{book_id}/journal").json()]
    # The day keeps its finish, the restart and its last position; today is untouched.
    assert kept == [("progress", "5"), ("progress", "2"), ("reset", "1"), ("finished", "40")]


def test_reading_statistics(api, book_id):
    client, session_factory = api
    for seq, page in enumerate((0, 9, 19), start=1):
        _save(client, book_id, page, "a", seq)
    _save(client, book_id, 39, "a", 4, is_finished=True)
    with session_factory() as db:
        # The first two reports were yesterday and the day before.
        today = dt.datetime.now(dt.UTC)
        for event in db.query(ReadingEvent).filter(ReadingEvent.client_seq < 3):
            event.received_at = today - dt.timedelta(days=3 - event.client_seq)
        db.commit()
    got = client.get("/api/me/reading-stats").json()
    assert (got["finished_total"], got["in_progress"], got["current_streak"], got["longest_streak"]) == (1, 0, 3, 3)
    assert got["pages"] == 39
    assert [d["pages"] for d in got["days"]] == [0, 9, 30]
    assert got["finished_by_month"][-1] == {"month": today.strftime("%Y-%m"), "count": 1}
    assert len(got["finished_by_month"]) == 12
    assert got["finished_by_type"] == {"comics": 1}
