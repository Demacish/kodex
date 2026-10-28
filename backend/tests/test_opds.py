"""The OPDS catalog (kodex.delivery.opds): OPDS 1.2 Atom feeds with Page
Streaming, OPDS 2.0 feeds validated against the specification's parser,
the Progression draft, and progress from the pages a PSE client fetches,
all with an OPDS key as the HTTP Basic password."""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from webpub_manifest_parser.opds2 import OPDS2FeedParserFactory

from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.models.metadata import BookMetadata
from app.models.series import Series
from app.models.user import User
from kodex.core.auth import keys
from kodex.delivery.opds import reports
from kodex.reading import journal
from tests.db import reset_database

ATOM = "{http://www.w3.org/2005/Atom}"
PSE = "{http://vaemendis.net/opds-pse/ns}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"


def _jpeg(label: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (300, 450), (label * 20 % 255, 80, 120)).save(out, "JPEG")
    return out.getvalue()


def _cbz(path, pages: int) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for page in range(pages):
            archive.writestr(f"{page + 1:03d}.jpg", _jpeg(page))


class Server:
    def __init__(self, client: TestClient, ids: dict[str, int], key: str) -> None:
        self.client, self.ids, self.key = client, ids, key

    def get(self, path: str, **kwargs):
        return self.client.get(path, auth=("vem-som-helst", self.key), **kwargs)

    def put(self, path: str, **kwargs):
        return self.client.put(path, auth=("vem-som-helst", self.key), **kwargs)


@pytest.fixture
def opds(tmp_path, monkeypatch):
    reset_database()
    reports.forget()
    root = tmp_path / "libraries"
    (root / "serier" / "Stjärnhavet").mkdir(parents=True)
    monkeypatch.setenv("LIBRARIES_ROOT", str(root))
    monkeypatch.setenv("COVERS_DIR", str(tmp_path / "covers"))
    monkeypatch.setenv("AUTH_DISABLED", "false")
    get_settings.cache_clear()
    with SessionLocal() as db:
        user = User(username="anna", role="user")
        db.add(user)
        db.flush()
        _, key = keys.create(db, user, "Läsplattan", "opds")
        library = Library(name="Serier", path="serier", library_type=LibraryType.COMICS)
        db.add(library)
        db.flush()
        series = Series(library_id=library.id, title="Stjärnhavet", sort_title="Stjärnhavet", path="Stjärnhavet")
        db.add(series)
        db.flush()
        ids = {"library": library.id, "series": series.id, "user": user.id}
        for number in (1, 2, 3):
            name = f"Stjärnhavet/Stjärnhavet {number:03d}.cbz"
            _cbz(root / "serier" / name, 10)
            book = Book(library_id=library.id, series_id=series.id, file_path=name, file_format=BookFormat.CBZ,
                        file_size=(root / "serier" / name).stat().st_size, file_mtime=0.0, page_count=10,
                        number=float(number))  # fmt: skip
            db.add(book)
            db.flush()
            db.add(BookMetadata(book_id=book.id, title=f"Stjärnhavet #{number}", sort_title=f"Stjärnhavet {number}",
                                authors=["Ingrid Berg"], genres=["Äventyr"], language="sv"))  # fmt: skip
            ids[f"book{number}"] = book.id
        db.commit()
    with TestClient(app, base_url="https://kodex.test") as client:
        yield Server(client, ids, key)
    get_settings.cache_clear()


def _feed(response) -> ET.Element:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/atom+xml;profile=opds-catalog")
    return ET.fromstring(response.content)


def _titles(feed: ET.Element) -> list[str]:
    return [entry.findtext(f"{ATOM}title") for entry in feed.findall(f"{ATOM}entry")]


def _positions(server: Server, book: int) -> list[tuple[str | None, str | None]]:
    with SessionLocal() as db:
        return [(e.position, e.device_name) for e in journal.entries(db, server.ids["user"], book)]


def test_an_opds_key_is_the_password(opds):
    assert opds.client.get("/opds/").status_code == 401
    assert opds.client.get("/opds/").headers["www-authenticate"] == "Basic"
    assert opds.client.get("/opds/", auth=("anna", "kdx_wrong")).status_code == 401
    assert opds.get("/opds/").status_code == 200


def test_the_start_lists_shelves_and_libraries(opds):
    feed = _feed(opds.get("/opds/"))
    assert _titles(feed) == ["Läser nu", "Nytt", "Följda serier", "Serier"]
    search = [link for link in feed.findall(f"{ATOM}link") if link.get("rel") == "search"]
    assert search[0].get("href") == "/opds/search-description.xml"


def test_a_series_feed_has_acquisition_and_page_streaming(opds):
    library = _feed(opds.get(f"/opds/libraries/{opds.ids['library']}"))
    assert _titles(library) == ["Stjärnhavet"]
    feed = _feed(opds.get(f"/opds/series/{opds.ids['series']}"))
    assert _titles(feed) == ["Stjärnhavet #1", "Stjärnhavet #2", "Stjärnhavet #3"]
    entry = feed.findall(f"{ATOM}entry")[0]
    assert entry.findtext(f"{ATOM}author/{ATOM}name") == "Ingrid Berg"
    links = {link.get("rel"): link for link in entry.findall(f"{ATOM}link")}
    acquisition = links["http://opds-spec.org/acquisition"]
    assert acquisition.get("type") == "application/vnd.comicbook+zip" and int(acquisition.get("length")) > 0
    stream = links["http://vaemendis.net/opds-pse/stream"]
    assert stream.get("href") == f"/opds/books/{opds.ids['book1']}/pages/{{pageNumber}}?width={{maxWidth}}"
    assert stream.get(f"{PSE}count") == "10" and stream.get(f"{PSE}lastRead") is None


def test_files_covers_and_pages_download(opds):
    book = opds.ids["book1"]
    file = opds.get(f"/opds/books/{book}/file")
    assert file.status_code == 200 and zipfile.is_zipfile(io.BytesIO(file.content))
    assert "Stj" in file.headers["content-disposition"]
    cover = opds.get(f"/opds/books/{book}/cover?size=medium")
    assert cover.headers["content-type"] == "image/jpeg" and cover.content[:3] == b"\xff\xd8\xff"
    page = opds.get(f"/opds/books/{book}/pages/2?width=200")
    assert page.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(page.content)).width <= 480
    unfilled = opds.get(f"/opds/books/{book}/pages/3?width={{maxWidth}}")
    assert unfilled.status_code == 200 and Image.open(io.BytesIO(unfilled.content)).width == 300
    assert opds.get(f"/opds/books/{book}/pages/10").status_code == 404


def test_reading_page_by_page_is_progress(opds, monkeypatch):
    clock = iter([100.0, 103.0, 103.5, 108.0])
    monkeypatch.setattr(reports, "_clock", lambda: next(clock))
    book = opds.ids["book2"]
    for page in (0, 1, 2, 3):  # 2 comes right after 1: a prefetch, not reading
        assert opds.get(f"/opds/books/{book}/pages/{page}").status_code == 200
    assert _positions(opds, book) == [("3", "Läsplattan"), ("1", "Läsplattan"), ("0", "Läsplattan")]
    feed = _feed(opds.get(f"/opds/series/{opds.ids['series']}"))
    stream = [link for link in feed.findall(f"{ATOM}entry")[1].findall(f"{ATOM}link")
              if link.get("rel") == "http://vaemendis.net/opds-pse/stream"][0]  # fmt: skip
    assert stream.get(f"{PSE}lastRead") == "3"
    assert _titles(_feed(opds.get("/opds/reading"))) == ["Stjärnhavet #2"]


def test_a_whole_book_downloaded_by_pages_is_not_read(opds):
    book = opds.ids["book3"]
    for page in range(10):
        opds.get(f"/opds/books/{book}/pages/{page}")
    assert [position for position, _ in _positions(opds, book)] == ["0"]


def test_search_and_its_description(opds):
    description = ET.fromstring(opds.get("/opds/search-description.xml").content)
    assert description.find(f"{OPENSEARCH}Url").get("template") == "/opds/search?q={searchTerms}"
    assert _titles(_feed(opds.get("/opds/search", params={"q": "stjärn 2"}))) == ["Stjärnhavet #2"]
    everything = ["Stjärnhavet #1", "Stjärnhavet #2", "Stjärnhavet #3"]
    assert _titles(_feed(opds.get("/opds/search", params={"q": "berg"}))) == everything
    assert _titles(_feed(opds.get("/opds/search", params={"q": "ingenting"}))) == []


def test_long_feeds_come_in_pages(opds):
    with SessionLocal() as db:
        for number in range(4, 64):
            db.add(Book(library_id=opds.ids["library"], series_id=opds.ids["series"], file_path=f"x{number}.cbz",
                        file_format=BookFormat.CBZ, file_size=1, file_mtime=0.0, number=float(number)))  # fmt: skip
        db.commit()
    first = _feed(opds.get(f"/opds/series/{opds.ids['series']}"))
    assert len(first.findall(f"{ATOM}entry")) == 50
    assert first.findtext(f"{OPENSEARCH}totalResults") == "63"
    links = {link.get("rel"): link.get("href") for link in first.findall(f"{ATOM}link")}
    assert links["next"] == f"/opds/series/{opds.ids['series']}?page=2"
    second = _feed(opds.get(links["next"]))
    assert len(second.findall(f"{ATOM}entry")) == 13


_parser = OPDS2FeedParserFactory().create()


def _opds2(response) -> dict:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/opds+json"
    body = response.json()
    assert [str(e) for e in _parser.parse_json(body).errors] == []
    return body


def test_opds2_feeds_follow_the_specification(opds):
    home = _opds2(opds.get("/opds/v2/catalog"))
    assert [n["title"] for n in home["navigation"]] == ["Läser nu", "Nytt", "Följda serier", "Serier"]
    assert home["links"][0]["href"] == "https://kodex.test/opds/v2/catalog"
    assert [g["metadata"]["title"] for g in home["groups"]] == ["Nytt"]
    library = _opds2(opds.get(f"/opds/v2/libraries/{opds.ids['library']}"))
    assert [n["title"] for n in library["navigation"]] == ["Stjärnhavet"]
    series = _opds2(opds.get(f"/opds/v2/series/{opds.ids['series']}"))
    first = series["publications"][0]
    assert first["metadata"]["title"] == "Stjärnhavet #1"
    assert first["metadata"]["belongsTo"]["series"][0]["position"] == 1.0
    rels = {link["rel"] for link in first["links"]}
    assert {"http://opds-spec.org/acquisition", "http://www.cantook.com/api/progression"} <= rels
    search = _opds2(opds.get("/opds/v2/search", params={"query": "stjärnhavet 3"}))
    assert [p["metadata"]["title"] for p in search["publications"]] == ["Stjärnhavet #3"]


def test_progression_goes_both_ways(opds):
    book = opds.ids["book1"]
    assert opds.get(f"/opds/v2/books/{book}/progression").status_code == 204
    sent = {"modified": "2026-10-26T12:00:00Z", "device": {"id": "ipad-1", "name": "Kodex på iPad"},
            "locator": {"href": "x", "type": "image/jpeg", "locations": {"position": 6, "totalProgression": 0.6}}}  # fmt: skip
    assert opds.put(f"/opds/v2/books/{book}/progression", json=sent).status_code == 204
    got = opds.get(f"/opds/v2/books/{book}/progression").json()
    assert got["locator"]["locations"] == {"totalProgression": 0.6, "progression": 0.6, "position": 6}
    assert got["locator"]["href"] == f"https://kodex.test/opds/books/{book}/pages/5"
    assert got["device"]["name"] == "Kodex på iPad"
    with SessionLocal() as db:
        current = journal.current(db, opds.ids["user"], book)
        assert (current.locator_kind, current.position, current.progress_percent) == ("page", "5", 60.0)
    opds.put(f"/opds/v2/books/{book}/progression", json={"locator": {"locations": {"totalProgression": 1.0}}})
    assert opds.get(f"/opds/v2/books/{book}").json()["metadata"]["readingProgress"] == 1.0
