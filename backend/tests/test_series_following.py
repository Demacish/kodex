"""Tests for "Följda serier" — a series automatically marked as followed
the first time reading progress is saved on one of its books (see
app/api/routes/reading_progress.py and Series.is_following), plus the
GET /series `following` filter and the admin-triggered
POST /series/check-releases (app/api/routes/series.py). The actual weekly
release-check logic itself is covered separately in
test_release_check.py — these tests are about the surrounding API/model
wiring, not the Comic Vine/AniList calls.
"""

from __future__ import annotations

from app.auth import get_current_user, require_admin
from app.main import app
from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.models.series import Series
from app.models.user import User


def _seed_series_book(session_factory, *, suffix: str = "") -> tuple[int, int]:
    db = session_factory()
    library = Library(name=f"Serier{suffix}", path=f"serier{suffix}", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    series = Series(
        library_id=library.id,
        title=f"One Piece{suffix}",
        sort_title=f"One Piece{suffix}",
        path=f"One Piece{suffix}",
    )
    db.add(series)
    db.flush()
    book = Book(
        library_id=library.id,
        series_id=series.id,
        file_path="One Piece 001.cbz",
        file_format=BookFormat.CBZ,
        file_size=10,
        file_mtime=0.0,
        number=1,
    )
    db.add(book)
    db.commit()
    book_id, series_id = book.id, series.id
    db.close()
    return book_id, series_id


def _seed_standalone_book(session_factory) -> int:
    db = session_factory()
    library = Library(name="E-böcker", path="ebooks", library_type=LibraryType.EBOOKS)
    db.add(library)
    db.flush()
    book = Book(
        library_id=library.id, file_path="standalone.epub", file_format=BookFormat.EPUB, file_size=1, file_mtime=0.0
    )
    db.add(book)
    db.commit()
    book_id = book.id
    db.close()
    return book_id


def test_saving_progress_marks_series_as_following(api):
    client, session_factory = api
    book_id, series_id = _seed_series_book(session_factory)

    series_before = client.get(f"/series/{series_id}").json()
    assert series_before["is_following"] is False
    assert series_before["followed_at"] is None

    response = client.put(f"/books/{book_id}/progress", json={"position": "1", "progress_percent": 10})
    assert response.status_code == 200

    series_after = client.get(f"/series/{series_id}").json()
    assert series_after["is_following"] is True
    assert series_after["followed_at"] is not None


def test_saving_progress_again_does_not_reset_followed_at(api):
    client, session_factory = api
    book_id, series_id = _seed_series_book(session_factory)

    client.put(f"/books/{book_id}/progress", json={"position": "1", "progress_percent": 10})
    first = client.get(f"/series/{series_id}").json()["followed_at"]

    client.put(f"/books/{book_id}/progress", json={"position": "2", "progress_percent": 20})
    second = client.get(f"/series/{series_id}").json()["followed_at"]

    assert first == second


def test_saving_progress_on_standalone_book_touches_no_series(api):
    client, session_factory = api
    book_id = _seed_standalone_book(session_factory)

    response = client.put(f"/books/{book_id}/progress", json={"position": "1", "progress_percent": 10})
    assert response.status_code == 200


def test_series_following_filter(api):
    client, session_factory = api
    _, followed_series_id = _seed_series_book(session_factory, suffix="-a")
    _, unfollowed_series_id = _seed_series_book(session_factory, suffix="-b")

    db = session_factory()
    series = db.get(Series, followed_series_id)
    series.is_following = True
    series.new_release_available = True
    db.add(series)
    db.commit()
    db.close()

    following = client.get("/series?following=true").json()
    assert [s["id"] for s in following] == [followed_series_id]
    assert following[0]["new_release_available"] is True

    not_following = client.get("/series?following=false").json()
    assert [s["id"] for s in not_following] == [unfollowed_series_id]


def test_empty_series_hidden_from_list(api):
    client, session_factory = api
    _, series_with_book_id = _seed_series_book(session_factory, suffix="-c")

    db = session_factory()
    library = Library(name="Serier-empty", path="serier-empty", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    empty_series = Series(library_id=library.id, title="Tom serie", sort_title="Tom serie", path="Tom serie")
    db.add(empty_series)
    db.commit()
    empty_series_id = empty_series.id
    db.close()

    ids = [s["id"] for s in client.get("/series").json()]
    assert series_with_book_id in ids
    assert empty_series_id not in ids


def test_read_status_and_paging_are_applied_before_the_page(api):
    client, session_factory = api
    db = session_factory()
    library = Library(name="Serier-status", path="serier-status", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    book_ids = {}
    for title in ("Alfa", "Beta", "Gamma", "Delta"):
        series = Series(library_id=library.id, title=title, sort_title=title, path=title)
        db.add(series)
        db.flush()
        books = [
            Book(library_id=library.id, series_id=series.id, file_path=f"{title} {n}.cbz", file_format=BookFormat.CBZ,
                 file_size=1, file_mtime=0.0, number=n)
            for n in (1, 2)
        ]  # fmt: skip
        db.add_all(books)
        db.flush()
        book_ids[title] = [book.id for book in books]
    db.commit()
    library_id = library.id
    db.close()
    for book_id in book_ids["Alfa"]:
        client.put(f"/books/{book_id}/progress", json={"position": "9", "progress_percent": 100, "is_finished": True})
    client.put(f"/books/{book_ids['Gamma'][0]}/progress", json={"position": "1", "progress_percent": 10})

    def titles(query: str) -> list[str]:
        return [s["title"] for s in client.get(f"/series?library_id={library_id}&{query}").json()]

    assert titles("read_status=read") == ["Alfa"]
    assert titles("read_status=in_progress") == ["Gamma"]
    assert titles("read_status=unread") == ["Beta", "Delta"]
    assert titles("read_status=unread&limit=1&offset=1") == ["Delta"]
    assert titles("limit=2&offset=1") == ["Beta", "Delta"]
    assert titles("sort=title&order=desc&limit=1") == ["Gamma"]


def test_follow_series_sets_is_following_and_followed_at(api):
    client, session_factory = api
    _, series_id = _seed_series_book(session_factory)

    response = client.post(f"/series/{series_id}/follow")

    assert response.status_code == 200
    body = response.json()
    assert body["is_following"] is True
    assert body["followed_at"] is not None


def test_follow_series_is_idempotent_and_keeps_first_followed_at(api):
    client, session_factory = api
    _, series_id = _seed_series_book(session_factory)

    first = client.post(f"/series/{series_id}/follow").json()["followed_at"]
    second = client.post(f"/series/{series_id}/follow").json()["followed_at"]

    assert first == second


def test_unfollow_series_clears_is_following_but_keeps_followed_at(api):
    client, session_factory = api
    _, series_id = _seed_series_book(session_factory)

    followed_at = client.post(f"/series/{series_id}/follow").json()["followed_at"]
    response = client.post(f"/series/{series_id}/unfollow")

    assert response.status_code == 200
    body = response.json()
    assert body["is_following"] is False
    # followed_at is deliberately preserved as "first followed" history —
    # see app/api/routes/series.py's unfollow_series docstring.
    assert body["followed_at"] == followed_at


def test_follow_unknown_series_returns_404(api):
    client, _ = api
    assert client.post("/series/999999/follow").status_code == 404
    assert client.post("/series/999999/unfollow").status_code == 404


def test_check_releases_requires_admin(api):
    client, _ = api
    non_admin = User(id=2, oidc_subject="non-admin-sub", username="reader", is_admin=False)
    app.dependency_overrides[get_current_user] = lambda: non_admin
    del app.dependency_overrides[require_admin]

    response = client.post("/series/check-releases")
    assert response.status_code == 403


def test_check_releases_enqueues_job(api, monkeypatch):
    client, _ = api

    class _FakeJob:
        id = "release-check-job-id"

    class _FakeQueue:
        def __init__(self):
            self.calls = []

        def enqueue(self, func, **kwargs):
            self.calls.append(func)
            return _FakeJob()

    fake_queue = _FakeQueue()
    monkeypatch.setattr("app.api.routes.series.get_enrichment_queue", lambda: fake_queue)

    response = client.post("/series/check-releases")

    assert response.status_code == 202
    assert response.json() == {"job_id": "release-check-job-id"}
    assert len(fake_queue.calls) == 1
