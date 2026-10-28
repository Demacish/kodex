"""The four services, each behind the same small interface: sign in,
search, read one entry, save progress. Calls go out with httpx; nothing
else in Kodex talks to these services as a user.

Progress is one number in the series' unit: volumes or chapters read.
Kitsu keeps chapters only, so a series read by volume there sends just
its status.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, ClassVar, Literal
from urllib.parse import urlencode

import httpx

USER_AGENT = "Kodex (self-hosted library server)"
Unit = Literal["volume", "chapter"]


class TrackerError(Exception):
    """The service said no, or didn't answer; the message is for people."""


class Expired(TrackerError):
    """The service no longer takes the account's token: connect it again."""


@dataclass
class Tokens:
    access: str
    refresh: str | None = None
    expires_at: dt.datetime | None = None


@dataclass
class Identity:
    id: str | None
    name: str


@dataclass
class Hit:
    id: str
    title: str
    year: int | None = None
    url: str | None = None
    cover: str | None = None
    volumes: int | None = None
    chapters: int | None = None


@dataclass
class Entry:
    """What the service has for the account: progress in both units, and the series' length when it knows it."""

    volumes: int = 0
    chapters: int = 0
    completed: bool = False
    total_volumes: int | None = None
    total_chapters: int | None = None
    #: False for a series not on the account's list yet, when the service still told its length.
    listed: bool = True

    def progress(self, unit: Unit) -> int:
        return self.volumes if unit == "volume" else self.chapters

    def total(self, unit: Unit) -> int | None:
        return self.total_volumes if unit == "volume" else self.total_chapters


def http_client() -> httpx.Client:
    """The client every service calls with (replaced in the tests)."""
    return httpx.Client(timeout=20.0, headers={"User-Agent": USER_AGENT})


def _expires(seconds: Any) -> dt.datetime | None:
    return dt.datetime.now(dt.UTC) + dt.timedelta(seconds=int(seconds)) if seconds else None


class Service:
    name: ClassVar[str]
    title: ClassVar[str]
    login: ClassVar[Literal["password", "oauth"]]
    units: ClassVar[tuple[Unit, ...]] = ("volume", "chapter")
    #: The names of an external id (kodex.matching) that are this service's ids.
    external_ids: ClassVar[tuple[str, ...]] = ()

    def __init__(self, http: httpx.Client | None = None) -> None:
        self.http = http or http_client()

    @classmethod
    def configured(cls) -> bool:
        return True

    def _check(self, response: httpx.Response) -> httpx.Response:
        if response.status_code == 401:
            raise Expired(f"{self.title} no longer accepts the login; connect the account again")
        if response.status_code >= 400:
            raise TrackerError(f"{self.title} answered {response.status_code}")
        return response

    # Password services.
    def sign_in(self, username: str, password: str) -> tuple[Tokens, Identity]:
        raise NotImplementedError

    # OAuth services.
    def authorize_url(self, redirect_uri: str, state: str, verifier: str) -> str:
        raise NotImplementedError

    def exchange(self, code: str, redirect_uri: str, verifier: str) -> tuple[Tokens, Identity]:
        raise NotImplementedError

    def refresh(self, tokens: Tokens) -> Tokens | None:
        """New tokens for expiring ones; None when the service has no refresh."""
        return None

    def search(self, tokens: Tokens, query: str) -> list[Hit]:
        raise NotImplementedError

    def entry(self, tokens: Tokens, user_id: str | None, remote_id: str) -> Entry | None:
        """The account's entry for the series; None when it isn't on its list."""
        raise NotImplementedError

    def save(self, tokens: Tokens, user_id: str | None, remote_id: str, unit: Unit, progress: int,
             completed: bool) -> None:  # fmt: skip
        raise NotImplementedError


class MangaUpdates(Service):
    name = "mangaupdates"
    title = "MangaUpdates"
    login = "password"
    external_ids = ("mangaupdates",)
    base = "https://api.mangaupdates.com/v1"
    READING, COMPLETE = 0, 2  # its built-in lists

    def _auth(self, tokens: Tokens) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens.access}"}

    def sign_in(self, username: str, password: str) -> tuple[Tokens, Identity]:
        response = self.http.put(f"{self.base}/account/login", json={"username": username, "password": password})
        if response.status_code in (400, 401):
            raise TrackerError("MangaUpdates didn't accept the username or password")
        context = self._check(response).json().get("context") or {}
        token = context.get("session_token")
        if not token:
            raise TrackerError("MangaUpdates didn't accept the username or password")
        return Tokens(token), Identity(str(context.get("uid")) if context.get("uid") else None, username)

    def search(self, tokens: Tokens, query: str) -> list[Hit]:
        response = self._check(self.http.post(f"{self.base}/series/search", json={"search": query, "perpage": 10}))
        hits = []
        for result in response.json().get("results") or []:
            record = result.get("record") or {}
            year = str(record.get("year") or "")
            hits.append(Hit(id=str(record.get("series_id")), title=str(record.get("title") or ""),
                            year=int(year[:4]) if year[:4].isdigit() else None, url=record.get("url"),
                            cover=((record.get("image") or {}).get("url") or {}).get("thumb")))  # fmt: skip
        return hits

    def entry(self, tokens: Tokens, user_id: str | None, remote_id: str) -> Entry | None:
        response = self.http.get(f"{self.base}/lists/series/{remote_id}", headers=self._auth(tokens))
        if response.status_code == 404:
            return None
        body = self._check(response).json()
        status = body.get("status") or {}
        return Entry(volumes=int(status.get("volume") or 0), chapters=int(status.get("chapter") or 0),
                     completed=body.get("list_id") == self.COMPLETE)  # fmt: skip

    def save(self, tokens: Tokens, user_id: str | None, remote_id: str, unit: Unit, progress: int,
             completed: bool) -> None:  # fmt: skip
        current = self.entry(tokens, user_id, remote_id)
        list_id = self.COMPLETE if completed else self.READING
        series = {"id": int(remote_id)}
        if current is None:
            self._check(self.http.post(f"{self.base}/lists/series", headers=self._auth(tokens),
                                       json=[{"series": series, "list_id": list_id}]))  # fmt: skip
            current = Entry()
        status = {"volume": current.volumes, "chapter": current.chapters}
        status[unit] = progress
        self._check(self.http.post(f"{self.base}/lists/series/update", headers=self._auth(tokens),
                                   json=[{"series": series, "list_id": list_id, "status": status}]))  # fmt: skip


class Kitsu(Service):
    name = "kitsu"
    title = "Kitsu"
    login = "password"
    units = ("chapter",)
    external_ids = ("kitsu",)
    base = "https://kitsu.app/api"
    _json_api = {"Accept": "application/vnd.api+json", "Content-Type": "application/vnd.api+json"}

    def _client(self) -> dict[str, str]:
        from app.config import get_settings

        settings = get_settings()
        if not settings.kitsu_client_id:
            return {}
        return {"client_id": settings.kitsu_client_id, "client_secret": settings.kitsu_client_secret}

    def _tokens(self, form: dict[str, str]) -> Tokens:
        response = self.http.post(f"{self.base}/oauth/token", data={**form, **self._client()})
        if response.status_code in (400, 401):
            raise TrackerError("Kitsu didn't accept the email address or password")
        body = self._check(response).json()
        return Tokens(body["access_token"], body.get("refresh_token"), _expires(body.get("expires_in")))

    def _auth(self, tokens: Tokens) -> dict[str, str]:
        return {**self._json_api, "Authorization": f"Bearer {tokens.access}"}

    def sign_in(self, username: str, password: str) -> tuple[Tokens, Identity]:
        tokens = self._tokens({"grant_type": "password", "username": username, "password": password})
        me = self._check(
            self.http.get(f"{self.base}/edge/users", params={"filter[self]": "true"}, headers=self._auth(tokens))
        )
        data = (me.json().get("data") or [{}])[0]
        return tokens, Identity(data.get("id"), (data.get("attributes") or {}).get("name") or username)

    def refresh(self, tokens: Tokens) -> Tokens | None:
        if not tokens.refresh:
            return None
        return self._tokens({"grant_type": "refresh_token", "refresh_token": tokens.refresh})

    def search(self, tokens: Tokens, query: str) -> list[Hit]:
        response = self._check(self.http.get(f"{self.base}/edge/manga", params={"filter[text]": query, "page[limit]": 10},
                                             headers=self._json_api))  # fmt: skip
        hits = []
        for item in response.json().get("data") or []:
            a = item.get("attributes") or {}
            start = str(a.get("startDate") or "")
            hits.append(Hit(id=str(item.get("id")), title=a.get("canonicalTitle") or "",
                            year=int(start[:4]) if start[:4].isdigit() else None,
                            url=f"https://kitsu.app/manga/{a.get('slug')}" if a.get("slug") else None,
                            cover=(a.get("posterImage") or {}).get("small"), volumes=a.get("volumeCount"),
                            chapters=a.get("chapterCount")))  # fmt: skip
        return hits

    def _library_entry(self, tokens: Tokens, user_id: str | None, remote_id: str) -> dict[str, Any] | None:
        params = {"filter[userId]": user_id or "", "filter[mangaId]": remote_id}
        response = self._check(
            self.http.get(f"{self.base}/edge/library-entries", params=params, headers=self._auth(tokens))
        )
        data = response.json().get("data") or []
        return data[0] if data else None

    def entry(self, tokens: Tokens, user_id: str | None, remote_id: str) -> Entry | None:
        found = self._library_entry(tokens, user_id, remote_id)
        if found is None:
            return None
        a = found.get("attributes") or {}
        return Entry(chapters=int(a.get("progress") or 0), completed=a.get("status") == "completed")

    def save(self, tokens: Tokens, user_id: str | None, remote_id: str, unit: Unit, progress: int,
             completed: bool) -> None:  # fmt: skip
        attributes: dict[str, Any] = {"status": "completed" if completed else "current"}
        if unit == "chapter":
            attributes["progress"] = progress
        found = self._library_entry(tokens, user_id, remote_id)
        if found is None:
            body = {"data": {"type": "libraryEntries", "attributes": attributes, "relationships": {
                "user": {"data": {"type": "users", "id": user_id}},
                "media": {"data": {"type": "manga", "id": remote_id}}}}}  # fmt: skip
            self._check(self.http.post(f"{self.base}/edge/library-entries", json=body, headers=self._auth(tokens)))
        else:
            body = {"data": {"type": "libraryEntries", "id": found["id"], "attributes": attributes}}
            self._check(self.http.patch(f"{self.base}/edge/library-entries/{found['id']}", json=body,
                                        headers=self._auth(tokens)))  # fmt: skip


class AniList(Service):
    name = "anilist"
    title = "AniList"
    login = "oauth"
    external_ids = ("anilist",)
    graphql = "https://graphql.anilist.co"

    @classmethod
    def configured(cls) -> bool:
        from app.config import get_settings

        return bool(get_settings().anilist_client_id and get_settings().anilist_client_secret)

    def _query(self, tokens: Tokens | None, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {tokens.access}"} if tokens else {}
        response = self.http.post(self.graphql, json={"query": query, "variables": variables}, headers=headers)
        if response.status_code == 404:
            return {}
        return self._check(response).json().get("data") or {}

    def authorize_url(self, redirect_uri: str, state: str, verifier: str) -> str:
        from app.config import get_settings

        query = {"client_id": get_settings().anilist_client_id, "redirect_uri": redirect_uri,
                 "response_type": "code", "state": state}  # fmt: skip
        return f"https://anilist.co/api/v2/oauth/authorize?{urlencode(query)}"

    def exchange(self, code: str, redirect_uri: str, verifier: str) -> tuple[Tokens, Identity]:
        from app.config import get_settings

        settings = get_settings()
        response = self.http.post("https://anilist.co/api/v2/oauth/token", json={
            "grant_type": "authorization_code", "client_id": settings.anilist_client_id,
            "client_secret": settings.anilist_client_secret, "redirect_uri": redirect_uri, "code": code})  # fmt: skip
        body = self._check(response).json()
        tokens = Tokens(body["access_token"], body.get("refresh_token"), _expires(body.get("expires_in")))
        viewer = self._query(tokens, "query { Viewer { id name } }", {}).get("Viewer") or {}
        return tokens, Identity(str(viewer.get("id")) if viewer.get("id") else None, viewer.get("name") or "AniList")

    def search(self, tokens: Tokens, query: str) -> list[Hit]:
        data = self._query(None, """query ($q: String) { Page(perPage: 10) { media(search: $q, type: MANGA) {
            id title { userPreferred } startDate { year } coverImage { medium } volumes chapters siteUrl } } }""",
                           {"q": query})  # fmt: skip
        return [Hit(id=str(m["id"]), title=(m.get("title") or {}).get("userPreferred") or "",
                    year=(m.get("startDate") or {}).get("year"), url=m.get("siteUrl"),
                    cover=(m.get("coverImage") or {}).get("medium"), volumes=m.get("volumes"), chapters=m.get("chapters"))
                for m in (data.get("Page") or {}).get("media") or []]  # fmt: skip

    def entry(self, tokens: Tokens, user_id: str | None, remote_id: str) -> Entry | None:
        data = self._query(tokens, """query ($user: Int, $media: Int) { MediaList(userId: $user, mediaId: $media, type: MANGA) {
            status progress progressVolumes media { volumes chapters } } }""",
                           {"user": int(user_id or 0), "media": int(remote_id)})  # fmt: skip
        found = data.get("MediaList")
        if not found:
            return None
        media = found.get("media") or {}
        return Entry(volumes=found.get("progressVolumes") or 0, chapters=found.get("progress") or 0,
                     completed=found.get("status") == "COMPLETED", total_volumes=media.get("volumes"),
                     total_chapters=media.get("chapters"))  # fmt: skip

    def save(self, tokens: Tokens, user_id: str | None, remote_id: str, unit: Unit, progress: int,
             completed: bool) -> None:  # fmt: skip
        field = "progressVolumes" if unit == "volume" else "progress"
        self._query(tokens, f"""mutation ($media: Int, $status: MediaListStatus, $value: Int) {{
            SaveMediaListEntry(mediaId: $media, status: $status, {field}: $value) {{ id }} }}""",
                    {"media": int(remote_id), "status": "COMPLETED" if completed else "CURRENT", "value": progress})  # fmt: skip


class MyAnimeList(Service):
    name = "myanimelist"
    title = "MyAnimeList"
    login = "oauth"
    external_ids = ("mal",)
    api = "https://api.myanimelist.net/v2"
    oauth = "https://myanimelist.net/v1/oauth2"

    @classmethod
    def configured(cls) -> bool:
        from app.config import get_settings

        return bool(get_settings().myanimelist_client_id)

    def _client(self) -> dict[str, str]:
        from app.config import get_settings

        settings = get_settings()
        client = {"client_id": settings.myanimelist_client_id}
        if settings.myanimelist_client_secret:
            client["client_secret"] = settings.myanimelist_client_secret
        return client

    def _auth(self, tokens: Tokens) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens.access}"}

    def _tokens(self, form: dict[str, str]) -> Tokens:
        body = self._check(self.http.post(f"{self.oauth}/token", data={**form, **self._client()})).json()
        return Tokens(body["access_token"], body.get("refresh_token"), _expires(body.get("expires_in")))

    def authorize_url(self, redirect_uri: str, state: str, verifier: str) -> str:
        # MyAnimeList takes only the "plain" PKCE method: the challenge is the verifier.
        query = {"response_type": "code", "client_id": self._client()["client_id"], "state": state,
                 "redirect_uri": redirect_uri, "code_challenge": verifier, "code_challenge_method": "plain"}  # fmt: skip
        return f"{self.oauth}/authorize?{urlencode(query)}"

    def exchange(self, code: str, redirect_uri: str, verifier: str) -> tuple[Tokens, Identity]:
        tokens = self._tokens({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                               "code_verifier": verifier})  # fmt: skip
        me = self._check(self.http.get(f"{self.api}/users/@me", headers=self._auth(tokens))).json()
        return tokens, Identity(str(me.get("id")) if me.get("id") else None, me.get("name") or "MyAnimeList")

    def refresh(self, tokens: Tokens) -> Tokens | None:
        if not tokens.refresh:
            return None
        return self._tokens({"grant_type": "refresh_token", "refresh_token": tokens.refresh})

    def search(self, tokens: Tokens, query: str) -> list[Hit]:
        params: dict[str, str | int] = {"q": query[:64], "limit": 10, "fields": "num_volumes,num_chapters,start_date"}
        response = self._check(self.http.get(f"{self.api}/manga", params=params, headers=self._auth(tokens)))
        hits = []
        for item in response.json().get("data") or []:
            node = item.get("node") or {}
            start = str(node.get("start_date") or "")
            hits.append(Hit(id=str(node.get("id")), title=node.get("title") or "",
                            year=int(start[:4]) if start[:4].isdigit() else None,
                            url=f"https://myanimelist.net/manga/{node.get('id')}",
                            cover=(node.get("main_picture") or {}).get("medium"),
                            volumes=node.get("num_volumes") or None, chapters=node.get("num_chapters") or None))  # fmt: skip
        return hits

    def entry(self, tokens: Tokens, user_id: str | None, remote_id: str) -> Entry | None:
        params = {"fields": "my_list_status,num_volumes,num_chapters"}
        response = self.http.get(f"{self.api}/manga/{remote_id}", params=params, headers=self._auth(tokens))
        body = self._check(response).json()
        status = body.get("my_list_status")
        if not status:
            return Entry(listed=False, total_volumes=body.get("num_volumes") or None,
                         total_chapters=body.get("num_chapters") or None)  # fmt: skip
        return Entry(volumes=status.get("num_volumes_read") or 0, chapters=status.get("num_chapters_read") or 0,
                     completed=status.get("status") == "completed", total_volumes=body.get("num_volumes") or None,
                     total_chapters=body.get("num_chapters") or None)  # fmt: skip

    def save(self, tokens: Tokens, user_id: str | None, remote_id: str, unit: Unit, progress: int,
             completed: bool) -> None:  # fmt: skip
        form = {"status": "completed" if completed else "reading",
                "num_volumes_read" if unit == "volume" else "num_chapters_read": str(progress)}  # fmt: skip
        self._check(
            self.http.patch(f"{self.api}/manga/{remote_id}/my_list_status", data=form, headers=self._auth(tokens))
        )


SERVICES: dict[str, type[Service]] = {s.name: s for s in (MangaUpdates, Kitsu, AniList, MyAnimeList)}


def service(name: str, http: httpx.Client | None = None) -> Service | None:
    found = SERVICES.get(name)
    return found(http) if found else None
