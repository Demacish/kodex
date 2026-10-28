"""KOReader sync server (app/api/routes/kosync.py) and its rules
(app/progress/sync.py): the newest position wins and goes into the
reading journal, pages translate, EPUB positions stay KOReader's own."""

from __future__ import annotations

import hashlib

import pytest

from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.models.reading_progress import ReadingProgress
from app.models.user import User

TOKEN = "secret-opds-token"
KEY = hashlib.md5(TOKEN.encode()).hexdigest()
HEADERS = {"x-auth-user": "test", "x-auth-key": KEY, "accept": "application/vnd.koreader.v1+json"}


@pytest.fixture
def kosync(api):
    """The shared `api` client, but authenticating kosync's own way: the
    fixture's user (username "test") gets an OPDS token."""
    client, session_factory = api
    db = session_factory()
    user = db.query(User).one()
    user.opds_token = TOKEN
    library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
    db.add(library)
    db.flush()
    books = {}
    for name, fmt, pages in (
        ("cbz", BookFormat.CBZ, 40),
        ("pdf", BookFormat.PDF, 200),
        ("epub", BookFormat.EPUB, None),
    ):
        book = Book(
            library_id=library.id,
            file_path=f"b.{name}",
            file_format=fmt,
            file_size=1,
            file_mtime=0.0,
            page_count=pages,
            content_hash=f"hash-{name}",
        )
        db.add(book)
        db.flush()
        books[name] = book.id
    db.commit()
    db.close()
    return client, session_factory, books


def _local(session_factory, book_id):
    db = session_factory()
    try:
        row = db.query(ReadingProgress).filter(ReadingProgress.book_id == book_id).one_or_none()
        return None if row is None else (row.position, row.progress_percent, row.is_finished)
    finally:
        db.close()


def test_auth_uses_username_and_md5_of_opds_token(kosync):
    client, _, _ = kosync
    assert client.get("/kosync/users/auth", headers=HEADERS).json() == {"authorized": "OK"}
    wrong = client.get("/kosync/users/auth", headers={**HEADERS, "x-auth-key": hashlib.md5(b"nope").hexdigest()})
    assert wrong.status_code == 401
    assert "message" in wrong.json()
    assert client.get("/kosync/users/auth", headers={**HEADERS, "x-auth-user": "other"}).status_code == 401
    assert client.post("/kosync/users/create", json={"username": "x", "password": "y"}).status_code == 403


def test_page_numbers_translate_between_koreader_and_kodex(kosync):
    client, session_factory, books = kosync
    client.put(
        "/kosync/syncs/progress",
        headers=HEADERS,
        json={
            "document": "hash-cbz",
            "progress": "11",
            "percentage": 0.275,
            "device": "Kobo",
            "device_id": "k1",
        },
    )
    # KOReader page 11 (1-based) = Kodex image reader index 10.
    assert _local(session_factory, books["cbz"]) == ("10", 27.5, False)

    client.put(
        "/kosync/syncs/progress",
        headers=HEADERS,
        json={
            "document": "hash-pdf",
            "progress": "50",
            "percentage": 0.25,
            "device": "Kobo",
            "device_id": "k1",
        },
    )
    assert _local(session_factory, books["pdf"])[0] == "50"  # PDF pages are 1-based on both sides

    got = client.get("/kosync/syncs/progress/hash-cbz", headers=HEADERS).json()
    assert got["progress"] == "11"
    assert got["percentage"] == 0.275
    assert got["device_id"] == "k1"


def test_kodex_reader_progress_is_served_to_koreader(kosync):
    client, _, books = kosync
    client.put(f"/books/{books['cbz']}/progress", json={"position": "19", "progress_percent": 50})
    got = client.get("/kosync/syncs/progress/hash-cbz", headers=HEADERS).json()
    assert got["progress"] == "20"
    assert got["percentage"] == 0.5
    assert got["device"] == "Kodex"


def _put(client, document, progress, percentage, device="Kobo", device_id="k1"):
    body = {"document": document, "progress": progress, "percentage": percentage, "device": device,
            "device_id": device_id}  # fmt: skip
    return client.put("/kosync/syncs/progress", headers=HEADERS, json=body)


def test_the_newest_position_wins(kosync):
    client, session_factory, books = kosync
    _put(client, "hash-cbz", "20", 0.5)
    _put(client, "hash-cbz", "10", 0.25, device="Telefon", device_id="t1")  # read back a bit, elsewhere
    assert client.get("/kosync/syncs/progress/hash-cbz", headers=HEADERS).json()["progress"] == "10"
    assert _local(session_factory, books["cbz"])[0] == "9"


def test_finishing_and_reading_again(kosync):
    client, session_factory, books = kosync
    _put(client, "hash-cbz", "40", 1.0)
    assert _local(session_factory, books["cbz"])[2] is True
    _put(client, "hash-cbz", "2", 0.05)
    assert client.get("/kosync/syncs/progress/hash-cbz", headers=HEADERS).json()["progress"] == "2"
    assert _local(session_factory, books["cbz"]) == ("1", 5.0, False)
    kinds = [e["kind"] for e in client.get(f"/books/{books['cbz']}/journal").json()]
    assert kinds == ["reset", "finished"]


def test_koreader_reports_are_in_the_journal(kosync):
    client, _, books = kosync
    _put(client, "hash-cbz", "11", 0.275, device="Kobo Clara", device_id="kobo-1")
    entry = client.get(f"/books/{books['cbz']}/journal").json()[0]
    assert (entry["device_name"], entry["device_id"], entry["locator_kind"], entry["position"]) == (
        "Kobo Clara", "kobo-1", "page", "10")  # fmt: skip


def test_epub_positions_stay_koreader_s_own(kosync):
    client, session_factory, books = kosync
    xpointer = "/body/DocFragment[12]/body/div/p[3]/text().0"
    _put(client, "hash-epub", xpointer, 0.42)
    assert _local(session_factory, books["epub"]) == (xpointer, 42.0, False)
    progress = client.get(f"/books/{books['epub']}/progress").json()
    assert (progress["locator_kind"], progress["progress_percent"]) == ("xpointer", 42.0)  # the web opens it at 42 %

    # Read further in the web reader: KOReader can't open a CFI, so it gets
    # its own last XPointer; another Kodex server gets the newer progression.
    client.put(f"/books/{books['epub']}/progress", json={"position": "epubcfi(/6/14!/4/2/1:0)", "progress_percent": 60})
    assert client.get("/kosync/syncs/progress/hash-epub", headers=HEADERS).json()["progress"] == xpointer
    other = client.get("/kosync/syncs/progress/hash-epub", headers={**HEADERS, "x-kodex-client": "1"}).json()
    assert (other["progress"], other["percentage"]) == (None, 0.6)


def test_documents_without_a_local_book_are_still_stored(kosync):
    client, _, _ = kosync
    _put(client, "on-another-server", "5", 0.1, device="NAS", device_id="n1")
    assert client.get("/kosync/syncs/progress/on-another-server", headers=HEADERS).json()["progress"] == "5"
    assert client.get("/kosync/syncs/progress/unknown", headers=HEADERS).json() == {}
