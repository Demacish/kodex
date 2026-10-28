"""Kobo sync (kodex.reading.kobo) as a Kobo e-reader calls it: the
initialization, library sync with its token and pages, metadata, reading
state both ways, KEPUB downloads, covers, removing a book on the device,
the way on to Kobo's store, and the web's device settings."""

from __future__ import annotations

import base64
import io
import json
import shutil
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models.book import Book
from app.models.collection import Collection, collection_books
from app.models.enums import BookFormat, CollectionType, LibraryType
from app.models.library import Library
from app.models.metadata import BookMetadata
from app.models.user import User
from kodex.core.auth import keys, passwords
from kodex.reading import journal
from kodex.reading.kobo import api as kobo_api
from kodex.reading.kobo import store, sync
from kodex.reading.models import KoboDevice
from tests.db import reset_database

PASSWORD = "correct horse battery"
_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:uuid:{uuid}</dc:identifier><dc:title>{title}</dc:title><dc:language>sv</dc:language>
    <meta property="dcterms:modified">2026-01-01T00:00:00Z</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="c1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="cover" href="cover.jpg" media-type="image/jpeg" properties="cover-image"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
</package>"""
_XHTML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>{title}</title></head>
<body>{body}</body></html>"""


def _epub(path, title: str, number: int) -> None:
    cover = io.BytesIO()
    Image.new("RGB", (400, 600), (30 * number, 90, 140)).save(cover, "JPEG")
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        epub.writestr("META-INF/container.xml", '<?xml version="1.0"?><container version="1.0" '
                      'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile '
                      'full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')  # fmt: skip
        epub.writestr("content.opf", _OPF.format(uuid=f"00000000-0000-4000-8000-{number:012d}", title=title))
        epub.writestr("nav.xhtml", _XHTML.format(title=title, body='<nav epub:type="toc"><ol><li>'
                                                                   '<a href="chapter1.xhtml">Ett</a></li></ol></nav>'))  # fmt: skip
        epub.writestr(
            "chapter1.xhtml", _XHTML.format(title=title, body="<p>Det var en gång.</p><p>Sedan hände det.</p>")
        )
        epub.writestr("cover.jpg", cover.getvalue())


class Kobo:
    """A Kobo e-reader and a browser, for one user."""

    def __init__(self, client: TestClient, key: str, ids: dict[str, int]) -> None:
        self.client, self.key, self.ids = client, key, ids
        self.token: str | None = None

    def call(self, method: str, path: str, **kwargs):
        return self.client.request(method, f"/kobo/{self.key}{path}", **kwargs)

    def sync(self) -> list[dict]:
        headers = {"x-kobo-synctoken": self.token} if self.token else {}
        answer = self.call("GET", "/v1/library/sync", headers=headers)
        assert answer.status_code == 200, answer.text
        self.token = answer.headers["x-kobo-synctoken"]
        self.more = answer.headers.get("x-kobo-sync") == "continue"
        return answer.json()

    def web(self, method: str, path: str, **kwargs):
        return self.client.request(method, path, headers={"x-csrf-token": self.client.cookies.get("kodex_csrf") or ""},
                                   **kwargs)  # fmt: skip


@pytest.fixture
def kobo(tmp_path, monkeypatch):
    reset_database()
    root = tmp_path / "libraries"
    (root / "bocker").mkdir(parents=True)
    for name, value in (("LIBRARIES_ROOT", str(root)), ("COVERS_DIR", str(tmp_path / "covers")),
                        ("AUTH_DISABLED", "false"), ("KOBO_STORE_PROXY", "false")):  # fmt: skip
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    with SessionLocal() as db:
        user = User(username="anna", role="user", password_hash=passwords.hash_password(PASSWORD))
        db.add(user)
        db.flush()
        record, key = keys.create(db, user, "Kobo Clara", "kobo")
        device = kobo_api.device_for(db, record, user)
        library = Library(name="Böcker", path="bocker", library_type=LibraryType.EBOOKS)
        db.add(library)
        db.flush()
        ids = {"user": user.id, "collection": device.collection_id, "library": library.id}
        for number, title in enumerate(("Havets röst", "Skogens hjärta", "Bergets eko"), start=1):
            path = root / "bocker" / f"{title}.epub"
            _epub(path, title, number)
            book = Book(library_id=library.id, file_path=path.name, file_format=BookFormat.EPUB,
                        file_size=path.stat().st_size, file_mtime=0.0)  # fmt: skip
            db.add(book)
            db.flush()
            db.add(BookMetadata(book_id=book.id, title=title, sort_title=title, authors=["Maja Ström"]))
            ids[f"book{number}"] = book.id
        for number in (1, 2):
            db.execute(
                collection_books.insert().values(collection_id=device.collection_id, book_id=ids[f"book{number}"])
            )
        db.commit()
    with TestClient(app, base_url="https://kodex.test") as client:
        assert client.post("/api/auth/login", json={"username": "anna", "password": PASSWORD}).status_code == 200
        yield Kobo(client, key, ids)
    get_settings.cache_clear()


def _entitlements(items: list[dict], kind: str) -> list[dict]:
    return [item[kind] for item in items if kind in item]


def test_an_unknown_key_is_refused(kobo):
    assert kobo.client.get("/kobo/kdx_nope/v1/initialization").status_code == 401


def test_initialization_points_covers_here(kobo):
    answer = kobo.call("GET", "/v1/initialization")
    assert answer.headers["x-kobo-apitoken"] == "e30="
    resources = answer.json()["Resources"]
    assert resources["image_url_template"] == (
        f"https://kodex.test/kobo/{kobo.key}/v1/books/{{ImageId}}/thumbnail/{{Width}}/{{Height}}/false/image.jpg"
    )
    assert "library_sync" in resources


def test_the_first_sync_brings_the_collection(kobo):
    items = kobo.sync()
    new = _entitlements(items, "NewEntitlement")
    assert sorted(n["BookMetadata"]["Title"] for n in new) == ["Havets röst", "Skogens hjärta"]
    first = new[0]
    uuid = first["BookEntitlement"]["Id"]
    assert sync.book_id_of(uuid) in (kobo.ids["book1"], kobo.ids["book2"])
    download = first["BookMetadata"]["DownloadUrls"][0]
    assert download["Url"] == f"https://kodex.test/kobo/{kobo.key}/v1/books/{uuid}/file"
    assert download["Format"] == ("KEPUB" if shutil.which("kepubify") else "EPUB")
    assert first["BookMetadata"]["Contributors"] == ["Maja Ström"]
    assert first["ReadingState"]["StatusInfo"]["Status"] == "ReadyToRead"
    assert kobo.sync() == []  # nothing new


def test_books_come_and_go_with_the_collection(kobo):
    kobo.sync()
    with SessionLocal() as db:
        db.execute(collection_books.insert().values(collection_id=kobo.ids["collection"], book_id=kobo.ids["book3"]))
        db.execute(collection_books.delete().where(collection_books.c.book_id == kobo.ids["book1"]))
        db.commit()
    items = kobo.sync()
    assert [n["BookMetadata"]["Title"] for n in _entitlements(items, "NewEntitlement")] == ["Bergets eko"]
    removed = _entitlements(items, "ChangedEntitlement")
    assert [(sync.book_id_of(r["BookEntitlement"]["Id"]), r["BookEntitlement"]["IsRemoved"]) for r in removed] == [
        (kobo.ids["book1"], True)]  # fmt: skip
    assert kobo.sync() == []


def test_a_big_library_comes_a_page_at_a_time(kobo, monkeypatch):
    monkeypatch.setattr(sync, "PAGE", 1)
    assert len(kobo.sync()) == 1 and kobo.more
    assert len(kobo.sync()) == 1 and not kobo.more
    assert kobo.sync() == []


def test_a_device_that_starts_over_gets_everything_again(kobo):
    kobo.sync()
    kobo.token = None
    assert len(_entitlements(kobo.sync(), "NewEntitlement")) == 2


def test_reading_state_goes_both_ways(kobo):
    kobo.sync()
    uuid = sync.book_uuid(kobo.ids["book1"])
    state = {"ReadingStates": [{"EntitlementId": uuid, "StatusInfo": {"Status": "Reading"},
                                "CurrentBookmark": {"ProgressPercent": 42, "ContentSourceProgressPercent": 60,
                                                    "Location": {"Value": "kobo.3.1", "Type": "KoboSpan",
                                                                 "Source": "chapter1.xhtml"}}}]}  # fmt: skip
    answer = kobo.call("PUT", f"/v1/library/{uuid}/state", json=state)
    assert answer.json()["UpdateResults"][0]["CurrentBookmarkResult"] == {"Result": "Success"}
    with SessionLocal() as db:
        current = journal.current(db, kobo.ids["user"], kobo.ids["book1"])
        assert (current.locator_kind, current.progress_percent, current.device_name) == ("kobo", 42.0, "Kobo Clara")
    got = kobo.call("GET", f"/v1/library/{uuid}/state").json()[0]["CurrentBookmark"]
    assert got["Location"] == {"Value": "kobo.3.1", "Type": "KoboSpan", "Source": "chapter1.xhtml"}
    assert got["ContentSourceProgressPercent"] == 60
    assert kobo.sync() == []  # the device's own position isn't sent back

    # Read further in the web reader: the device gets the progression.
    kobo.web("PUT", f"/api/books/{kobo.ids['book1']}/progress",
             json={"position": "epubcfi(/6/2!/4/2:0)", "locator_kind": "cfi", "progress_percent": 70})  # fmt: skip
    changed = _entitlements(kobo.sync(), "ChangedReadingState")
    bookmark = changed[0]["ReadingState"]["CurrentBookmark"]
    assert bookmark["ProgressPercent"] == 70 and "Location" not in bookmark


def test_finishing_on_the_device(kobo):
    uuid = sync.book_uuid(kobo.ids["book2"])
    state = {"ReadingStates": [{"EntitlementId": uuid, "StatusInfo": {"Status": "Finished"}, "CurrentBookmark": {}}]}
    kobo.call("PUT", f"/v1/library/{uuid}/state", json=state)
    with SessionLocal() as db:
        current = journal.current(db, kobo.ids["user"], kobo.ids["book2"])
        assert (current.is_finished, current.progress_percent) == (True, 100.0)


def test_downloads_are_kepub_and_covers_jpeg(kobo):
    uuid = sync.book_uuid(kobo.ids["book1"])
    answer = kobo.call("GET", f"/v1/books/{uuid}/file")
    assert answer.status_code == 200 and zipfile.is_zipfile(io.BytesIO(answer.content))
    if shutil.which("kepubify"):
        assert "kepub.epub" in answer.headers["content-disposition"]
        assert b"koboSpan" in b"".join(zipfile.ZipFile(io.BytesIO(answer.content)).read(n) for n in
                                       zipfile.ZipFile(io.BytesIO(answer.content)).namelist() if n.endswith(".xhtml"))  # fmt: skip
    cover = kobo.call("GET", f"/v1/books/{uuid}/thumbnail/355/530/false/image.jpg")
    assert cover.headers["content-type"] == "image/jpeg" and cover.content[:3] == b"\xff\xd8\xff"
    elsewhere = kobo.call("GET", "/v1/books/store-image/thumbnail/355/530/false/image.jpg", follow_redirects=False)
    assert elsewhere.status_code == 307 and elsewhere.headers["location"].startswith(store.IMAGES)


def test_removing_a_book_on_the_device_takes_it_out_of_the_collection(kobo):
    kobo.sync()
    uuid = sync.book_uuid(kobo.ids["book2"])
    assert kobo.call("DELETE", f"/v1/library/{uuid}").status_code == 204
    with SessionLocal() as db:
        collection = db.get(Collection, kobo.ids["collection"])
        assert [b.id for b in collection.books] == [kobo.ids["book1"]]
    assert kobo.sync() == []


def test_the_rest_goes_on_to_the_store(kobo, monkeypatch):
    monkeypatch.setenv("KOBO_STORE_PROXY", "true")
    get_settings.cache_clear()
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/v1/library/sync":
            return httpx.Response(200, json=[{"NewEntitlement": {"BookEntitlement": {"Id": "store-book"}}}],
                                  headers={"x-kobo-synctoken": "store-token-2"})  # fmt: skip
        if request.url.path == "/v1/user/profile":
            return httpx.Response(200, json={"Profile": "from the store"})
        return httpx.Response(404)

    monkeypatch.setattr(store, "client", lambda: httpx.Client(transport=httpx.MockTransport(answer)))
    profile = kobo.call("GET", "/v1/user/profile", headers={"authorization": "Bearer store-token"})
    assert profile.json() == {"Profile": "from the store"}
    assert seen[0].url.host == "storeapi.kobo.com" and seen[0].headers["authorization"] == "Bearer store-token"
    items = kobo.sync()
    assert items[0] == {"NewEntitlement": {"BookEntitlement": {"Id": "store-book"}}} and len(items) == 3
    assert json.loads(base64.b64decode(kobo.token))["store"] == "store-token-2"
    kobo.sync()
    assert seen[-1].headers["x-kobo-synctoken"] == "store-token-2"


def test_without_the_store_its_requests_get_empty_answers(kobo):
    assert kobo.call("GET", "/v1/user/profile").json() == {}
    auth = kobo.call("POST", "/v1/auth/device", json={"UserKey": "x"}).json()
    assert auth["TokenType"] == "Bearer" and auth["AccessToken"]


def test_the_web_chooses_what_a_device_syncs(kobo):
    devices = kobo.web("GET", "/api/me/kobo").json()
    assert [(d["name"], d["collection_name"]) for d in devices] == [("Kobo Clara", "Kobo")]
    with SessionLocal() as db:
        other = Collection(name="Semester", collection_type=CollectionType.MANUAL, owner_user_id=kobo.ids["user"])
        db.add(other)
        db.commit()
        other_id = other.id
    key_id = devices[0]["key_id"]
    changed = kobo.web("PUT", f"/api/me/kobo/{key_id}", json={"collection_id": other_id}).json()
    assert changed["collection_name"] == "Semester"
    with SessionLocal() as db:
        assert db.query(KoboDevice).one().collection_id == other_id
    assert kobo.sync() == []  # an empty collection
