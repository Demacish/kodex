"""GET /books' following_only / added_within_days filters — the home
page's "Nytt i serier du följer" shelf."""

from __future__ import annotations

import datetime as dt

from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.models.series import Series


def test_recent_unread_books_in_followed_series(api):
    client, session_factory = api
    db = session_factory()
    library = Library(name="Manga", path="manga", library_type=LibraryType.MANGA)
    db.add(library)
    db.flush()
    followed = Series(library_id=library.id, title="Bramble", sort_title="bramble", path="B", is_following=True)
    other = Series(library_id=library.id, title="Annat", sort_title="annat", path="A", is_following=False)
    db.add_all([followed, other])
    db.flush()
    now = dt.datetime.now(dt.UTC)

    def book(series, number, days_ago):
        b = Book(
            library_id=library.id,
            series_id=series.id,
            file_path=f"{series.path}/{number}.cbz",
            file_format=BookFormat.CBZ,
            file_size=1,
            file_mtime=0.0,
            number=number,
            added_at=now - dt.timedelta(days=days_ago),
        )
        db.add(b)
        db.flush()
        return b.id

    new_a, new_b, old, unfollowed, read = (
        book(followed, 371, 1),
        book(followed, 372, 0),
        book(followed, 1, 400),
        book(other, 5, 0),
        book(followed, 370, 2),
    )
    db.commit()
    db.close()
    client.put(f"/books/{read}/progress", json={"position": "9", "progress_percent": 100, "is_finished": True})

    shelf = client.get(
        "/books?following_only=true&added_within_days=60&read_status=unread&sort=added_at&order=desc&limit=12"
    ).json()

    assert [b["id"] for b in shelf] == [new_b, new_a]
    assert old not in [b["id"] for b in shelf] and unfollowed not in [b["id"] for b in shelf]


def test_home_section_key_is_accepted(api):
    client, _ = api
    response = client.put("/me", json={"home_sections": ["new_in_followed", "continue_reading"]})
    assert response.json()["home_sections"] == ["new_in_followed", "continue_reading"]
