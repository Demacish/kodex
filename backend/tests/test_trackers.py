"""Trackers (kodex.reading.trackers): connecting accounts, linking series,
and sending what was read, only forward, with the tokens kept encrypted.
The services are fakes answering the calls their APIs document."""

from __future__ import annotations

import datetime as dt
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models.book import Book
from app.models.enums import BookFormat, LibraryType
from app.models.library import Library
from app.models.reading_progress import ReadingProgress
from app.models.series import Series
from kodex.matching.models import SeriesExternalId
from kodex.reading.trackers import push, secrets, services
from kodex.reading.trackers.models import TrackerAccount, TrackerLink


class FakeServices:
    """Answers like MangaUpdates, AniList, MyAnimeList and Kitsu; remembers what was sent."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, object]] = []
        self.mu_list: dict[int, dict] = {}
        self.mal_status: dict | None = None
        self.status = 200

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        body = request.content.decode() if request.content else ""
        self.sent.append((request.method, url, body))
        if self.status != 200:
            return httpx.Response(self.status, json={"reason": "no"})
        if url.endswith("/v1/account/login"):
            credentials = json.loads(body)
            if credentials["password"] != "rätt":
                return httpx.Response(401, json={"status": "exception", "reason": "Invalid"})
            return httpx.Response(200, json={"status": "success", "context": {"session_token": "mu-token", "uid": 77}})
        if "/v1/lists/series/update" in url:
            for item in json.loads(body):
                self.mu_list[item["series"]["id"]] = item
            return httpx.Response(200, json={"status": "success"})
        if url.endswith("/v1/lists/series") and request.method == "POST":
            for item in json.loads(body):
                self.mu_list[item["series"]["id"]] = {**item, "status": {"volume": 0, "chapter": 0}}
            return httpx.Response(200, json={"status": "success"})
        if "/v1/lists/series/" in url:
            found = self.mu_list.get(int(url.rsplit("/", 1)[1]))
            return httpx.Response(200, json=found) if found else httpx.Response(404, json={"reason": "not in list"})
        if url.startswith("https://anilist.co/api/v2/oauth/token"):
            return httpx.Response(200, json={"access_token": "al-token", "expires_in": 31536000})
        if url.startswith("https://graphql.anilist.co"):
            query = json.loads(body)["query"]
            if "Viewer" in query:
                return httpx.Response(200, json={"data": {"Viewer": {"id": 5, "name": "anna_al"}}})
            if "MediaList(" in query:
                return httpx.Response(404, json={"data": {"MediaList": None}, "errors": [{"status": 404}]})
            return httpx.Response(200, json={"data": {"SaveMediaListEntry": {"id": 1}}})
        if url.startswith("https://myanimelist.net/v1/oauth2/token"):
            return httpx.Response(
                200, json={"access_token": "mal-new", "refresh_token": "mal-refresh-2", "expires_in": 2678400}
            )
        if url.startswith("https://api.myanimelist.net/v2/manga/") and request.method == "GET":
            return httpx.Response(200, json={"id": 13, "num_volumes": 3, "my_list_status": self.mal_status})
        if url.startswith("https://api.myanimelist.net/v2/manga/") and request.method == "PATCH":
            self.mal_status = {k: v[0] for k, v in parse_qs(body).items()}
            return httpx.Response(200, json=self.mal_status)
        return httpx.Response(404)


@pytest.fixture
def trackers(api, monkeypatch):
    client, session_factory = api
    monkeypatch.setenv("SECRET_KEY", "ett långt hemligt värde för testerna")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://kodex.test")
    get_settings.cache_clear()
    fake = FakeServices()
    monkeypatch.setattr(services, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(fake.handle)))
    with session_factory() as db:
        library = Library(name="Manga", path="manga", library_type=LibraryType.MANGA)
        db.add(library)
        db.flush()
        series = Series(library_id=library.id, title="Stjärnhavet", sort_title="Stjärnhavet", path="s")
        db.add(series)
        db.flush()
        db.add(SeriesExternalId(series_id=series.id, provider="mangaupdates", external_id="123"))
        books = []
        for number in (1, 2, 3):
            book = Book(library_id=library.id, series_id=series.id, file_path=f"s/{number}.cbz", file_format=BookFormat.CBZ,
                        file_size=1, file_mtime=0.0, number=float(number))  # fmt: skip
            db.add(book)
            db.flush()
            books.append(book.id)
        db.commit()
        ids = {"series": series.id, "books": books}
    yield client, session_factory, fake, ids
    get_settings.cache_clear()


def _finish(client, book_id: int) -> None:
    response = client.put(f"/api/books/{book_id}/progress", json={"progress_percent": 100, "is_finished": True})
    assert response.status_code == 200, response.text


def test_tokens_are_kept_encrypted(trackers, monkeypatch):
    sealed = secrets.seal("hemlig-token")
    assert "hemlig" not in sealed and secrets.open_(sealed) == "hemlig-token"
    monkeypatch.setenv("SECRET_KEY", "en annan nyckel")
    get_settings.cache_clear()
    assert secrets.open_(sealed) is None


def test_the_services_are_listed_with_what_they_need(trackers):
    client, *_ = trackers
    listed = client.get("/api/trackers").json()
    assert listed["available"] is True
    by_name = {s["name"]: s for s in listed["services"]}
    assert by_name["mangaupdates"]["login"] == "password" and by_name["mangaupdates"]["configured"] is True
    assert by_name["anilist"]["configured"] is False  # no client registered
    assert by_name["kitsu"]["units"] == ["chapter"]


def test_a_linked_series_sends_volumes_read_only_forward(trackers):
    client, session_factory, fake, ids = trackers
    assert (
        client.post("/api/trackers/mangaupdates/login", json={"username": "anna", "password": "fel"}).status_code == 401
    )
    connected = client.post("/api/trackers/mangaupdates/login", json={"username": "anna", "password": "rätt"})
    assert connected.status_code == 200 and connected.json()["username"] == "anna"
    with session_factory() as db:
        account = db.scalars(select(TrackerAccount)).one()
        assert account.remote_user_id == "77" and "mu-token" not in account.access_token

    _finish(client, ids["books"][0])
    _finish(client, ids["books"][2])  # volume 2 skipped: three volumes read all the same
    offered = client.get(f"/api/series/{ids['series']}/trackers").json()
    assert offered["progress"] == 3 and offered["default_unit"] == "volume"
    assert [(t["service"], t["suggested_id"], t["link"]) for t in offered["trackers"]] == [
        ("mangaupdates", "123", None)
    ]

    linked = client.put(f"/api/series/{ids['series']}/trackers/mangaupdates",
                        json={"remote_id": "123", "title": "Stjärnhavet", "unit": "volume"})  # fmt: skip
    assert linked.status_code == 200 and linked.json()["sent_progress"] == 3
    assert fake.mu_list[123]["status"] == {"volume": 3, "chapter": 0} and fake.mu_list[123]["list_id"] == 0

    fake.sent.clear()
    with session_factory() as db:
        assert push.push_all(db) == 0  # nothing new read
    assert fake.sent == []

    fake.mu_list[123]["status"]["volume"] = 9  # read further somewhere else
    with session_factory() as db:
        db.query(ReadingProgress).filter(ReadingProgress.book_id == ids["books"][1]).delete()
        db.commit()
    _finish(client, ids["books"][1])
    with session_factory() as db:
        link = db.scalars(select(TrackerLink)).one()
        link.sent_progress = 2
        db.commit()
        assert push.push_all(db) == 0
    assert fake.mu_list[123]["status"]["volume"] == 9  # never backwards


def test_anilist_connects_through_its_login_page(trackers, monkeypatch):
    client, session_factory, fake, _ = trackers
    monkeypatch.setenv("ANILIST_CLIENT_ID", "4711")
    monkeypatch.setenv("ANILIST_CLIENT_SECRET", "s")
    get_settings.cache_clear()
    url = client.post("/api/trackers/anilist/authorize").json()["url"]
    query = parse_qs(urlsplit(url).query)
    assert query["client_id"] == ["4711"]
    assert query["redirect_uri"] == ["https://kodex.test/api/trackers/anilist/callback"]
    wrong = client.get("/api/trackers/anilist/callback", params={"code": "c", "state": "fel"}, follow_redirects=False)
    assert wrong.status_code == 303 and "tracker_error=anilist" in wrong.headers["location"]
    back = client.get("/api/trackers/anilist/callback", params={"code": "c", "state": query["state"][0]},
                      follow_redirects=False)  # fmt: skip
    assert (
        back.status_code == 303 and back.headers["location"] == "https://kodex.test/settings?tracker=anilist#trackers"
    )
    with session_factory() as db:
        account = db.scalars(select(TrackerAccount).where(TrackerAccount.service == "anilist")).one()
        assert (account.username, account.remote_user_id) == ("anna_al", "5")
    again = client.get("/api/trackers/anilist/callback", params={"code": "c", "state": query["state"][0]},
                       follow_redirects=False)  # fmt: skip
    assert "tracker_error" in again.headers["location"]  # the state works once


def test_myanimelist_tokens_are_refreshed_before_they_expire(trackers, monkeypatch):
    client, session_factory, fake, ids = trackers
    monkeypatch.setenv("MYANIMELIST_CLIENT_ID", "mal-client")
    get_settings.cache_clear()
    with session_factory() as db:
        db.add(TrackerAccount(user_id=1, service="myanimelist", username="anna", access_token=secrets.seal("mal-old"),
                              refresh_token=secrets.seal("mal-refresh"),
                              expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(hours=2)))  # fmt: skip
        db.add(TrackerLink(user_id=1, series_id=ids["series"], service="myanimelist", remote_id="13", title="Stjärnhavet",
                           unit="volume"))  # fmt: skip
        db.commit()
    for book in ids["books"]:
        _finish(client, book)
    with session_factory() as db:
        assert push.push_all(db) == 1
        account = db.scalars(select(TrackerAccount).where(TrackerAccount.service == "myanimelist")).one()
        assert secrets.open_(account.access_token) == "mal-new"
    refresh = [body for method, url, body in fake.sent if url.endswith("/oauth2/token")]
    assert "grant_type=refresh_token" in refresh[0] and "refresh_token=mal-refresh" in refresh[0]
    assert fake.mal_status == {"status": "completed", "num_volumes_read": "3"}  # all three of three volumes


def test_kitsu_counts_chapters_only(trackers):
    client, session_factory, _, ids = trackers
    with session_factory() as db:
        db.add(TrackerAccount(user_id=1, service="kitsu", username="anna", access_token=secrets.seal("k")))
        db.commit()
    refused = client.put(f"/api/series/{ids['series']}/trackers/kitsu", json={"remote_id": "9", "unit": "volume"})
    assert refused.status_code == 422


def test_a_refused_token_is_kept_as_the_links_error(trackers):
    client, session_factory, fake, ids = trackers
    client.post("/api/trackers/mangaupdates/login", json={"username": "anna", "password": "rätt"})
    _finish(client, ids["books"][0])
    fake.status = 401
    linked = client.put(
        f"/api/series/{ids['series']}/trackers/mangaupdates", json={"remote_id": "123", "unit": "volume"}
    )
    assert linked.status_code == 200
    assert linked.json()["sent_progress"] == 0 and "connect the account again" in linked.json()["error"]


def test_without_a_secret_key_nothing_connects(trackers, monkeypatch):
    client, *_ = trackers
    monkeypatch.delenv("SECRET_KEY")
    get_settings.cache_clear()
    assert client.get("/api/trackers").json()["available"] is False
    assert client.post("/api/trackers/mangaupdates/login", json={"username": "a", "password": "b"}).status_code == 503


def test_disconnecting_forgets_the_links(trackers):
    client, session_factory, _, ids = trackers
    client.post("/api/trackers/mangaupdates/login", json={"username": "anna", "password": "rätt"})
    client.put(f"/api/series/{ids['series']}/trackers/mangaupdates", json={"remote_id": "123", "unit": "volume"})
    assert client.delete("/api/trackers/mangaupdates").status_code == 204
    with session_factory() as db:
        assert db.scalars(select(TrackerLink)).all() == [] and db.scalars(select(TrackerAccount)).all() == []
