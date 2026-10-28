"""Push notifications via ntfy for new volumes in followed series
(kodex/delivery/notify.py's notify_new_books, triggered from
scan_library_task)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.workers.tasks as tasks
import kodex.delivery.notify as notify
from app.models.book import Book
from app.models.enums import BookEditionType, BookFormat, LibraryType
from app.models.library import Library
from app.models.series import Series
from app.models.user import User


@pytest.fixture
def seeded(db_session, monkeypatch):
    sent: list[dict] = []

    def fake_post(url, json, headers, timeout):
        sent.append({"url": url, "json": json, "headers": headers})
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr(notify.httpx, "post", fake_post)
    settings = SimpleNamespace(
        ntfy_url="https://ntfy.example/", ntfy_token="tk", public_app_url="https://kodex.example"
    )
    monkeypatch.setattr(tasks, "get_settings", lambda: settings)

    db = db_session
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    followed = Series(library_id=library.id, title="Saga", sort_title="saga", path="Saga", is_following=True)
    other = Series(library_id=library.id, title="Annat", sort_title="annat", path="Annat", is_following=False)
    db.add_all([followed, other])
    db.add_all(
        [
            User(oidc_subject="a", username="anna", ntfy_topic="anna-kodex"),
            User(oidc_subject="b", username="bo", ntfy_topic=None),
        ]
    )
    db.flush()

    def book(series, number, edition=BookEditionType.ISSUE):
        b = Book(
            library_id=library.id,
            series_id=series.id,
            file_path=f"{series.path}/{number}.cbz",
            file_format=BookFormat.CBZ,
            file_size=1,
            file_mtime=0.0,
            number=number,
            edition_type=edition,
        )
        db.add(b)
        db.flush()
        return b.id

    ids = SimpleNamespace(
        saga55=book(followed, 55),
        saga56=book(followed, 56),
        saga_vol=book(followed, 9, BookEditionType.COLLECTED),
        other=book(other, 1),
    )
    db.commit()
    return SimpleNamespace(db=db, sent=sent, ids=ids, followed_id=followed.id)


def test_one_push_per_followed_series_to_users_with_a_topic(seeded):
    ids = seeded.ids
    count = tasks._notify_new_books_in_followed_series(seeded.db, [ids.saga56, ids.saga55, ids.saga_vol, ids.other])

    assert count == 1
    assert len(seeded.sent) == 1
    push = seeded.sent[0]
    assert push["url"] == "https://ntfy.example"
    assert push["headers"] == {"Authorization": "Bearer tk"}
    assert push["json"]["topic"] == "anna-kodex"
    assert push["json"]["title"] == "3 nya volymer i Saga"
    assert push["json"]["message"] == "#55, #56, Vol. 9"
    assert push["json"]["click"] == f"https://kodex.example/series/{seeded.followed_id}"


def test_single_volume_wording_and_nothing_for_unfollowed(seeded):
    assert tasks._notify_new_books_in_followed_series(seeded.db, [seeded.ids.other]) == 0
    tasks._notify_new_books_in_followed_series(seeded.db, [seeded.ids.saga55])
    assert seeded.sent[-1]["json"]["title"] == "Ny volym i Saga"


def test_a_failing_push_never_raises(seeded, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("ntfy down")

    monkeypatch.setattr(notify.httpx, "post", boom)
    assert tasks._notify_new_books_in_followed_series(seeded.db, [seeded.ids.saga55]) == 0


def test_profile_stores_and_validates_the_ntfy_topic(api):
    client, _ = api
    assert client.put("/me", json={"ntfy_topic": "mitt-amne_1"}).json()["ntfy_topic"] == "mitt-amne_1"
    assert client.put("/me", json={"ntfy_topic": "inte giltigt!"}).status_code == 422
    assert client.put("/me", json={"ntfy_topic": ""}).json()["ntfy_topic"] is None
