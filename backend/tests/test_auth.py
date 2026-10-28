"""The backend's own authentication (kodex.core.auth, ADR 0007): the first
admin, password logins and their throttling, session cookies with CSRF,
personal API keys for apps, OPDS and KOSync, roles, user management, the
command line, and an OpenID Connect login against a fake provider."""

from __future__ import annotations

import base64
import hashlib
import io
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import RSAKey

from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models.user import User
from kodex.core.auth import oidc, passwords
from kodex.core.auth import setup as first_admin
from tests.db import reset_database

PASSWORD = "correct horse battery"
_ISSUER = "https://idp.test/application/o/kodex/"


@pytest.fixture
def settings(monkeypatch):
    """Real settings from the environment, re-read for each test."""

    def apply(**values: object) -> None:
        for name, value in values.items():
            monkeypatch.setenv(name.upper(), str(value))
        get_settings.cache_clear()

    apply(auth_disabled="false", oidc_issuer="", oidc_client_id="")
    yield apply
    get_settings.cache_clear()


@pytest.fixture
def client(settings):
    reset_database()
    with TestClient(app, base_url="https://kodex.test") as test_client:
        yield test_client


def _csrf(client: TestClient) -> dict[str, str]:
    return {"x-csrf-token": client.cookies.get("kodex_csrf") or ""}


def _make_user(username: str, *, role: str = "user", password: str | None = PASSWORD, **fields) -> int:
    with SessionLocal() as db:
        user = User(username=username, role=role, is_admin=role == "admin",
                    password_hash=passwords.hash_password(password) if password else None, **fields)  # fmt: skip
        db.add(user)
        db.commit()
        return user.id


def _login(client: TestClient, username: str, password: str = PASSWORD) -> httpx.Response:
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_the_first_admin_is_made_once(client):
    assert client.get("/api/auth/config").json()["setup_required"] is True
    response = client.post("/api/auth/setup", json={"username": "Admin", "password": PASSWORD})
    assert response.status_code == 201
    assert (response.json()["role"], response.json()["is_admin"]) == ("admin", True)
    assert client.get("/api/auth/me").json()["username"] == "Admin"
    assert client.get("/api/auth/config").json()["setup_required"] is False
    again = client.post("/api/auth/setup", json={"username": "other", "password": PASSWORD})
    assert again.status_code == 409


def _announce() -> str | None:
    with SessionLocal() as db:
        return first_admin.announce(db)


def test_a_server_whose_admins_cant_log_in_is_set_up_with_the_code(client, caplog):
    # v1's accounts: an admin and a reader, neither with a password.
    admin_id = _make_user("Hans", role="admin", password=None)
    _make_user("reader", password=None)
    config = client.get("/api/auth/config").json()
    assert (config["setup_required"], config["setup_code_required"]) == (True, True)
    code = _announce()
    assert code and code in caplog.text

    def setup(**fields):
        return client.post("/api/auth/setup", json={"username": "hans", "password": PASSWORD, **fields})

    assert setup().status_code == 403
    assert setup(code="WRONG-CODE").status_code == 403
    response = setup(code=code.lower().replace("-", " "))
    assert response.status_code == 201
    assert (response.json()["id"], response.json()["username"], response.json()["is_admin"]) == (admin_id, "Hans", True)
    assert client.get("/api/auth/me").json()["username"] == "Hans"
    assert client.get("/api/auth/config").json()["setup_required"] is False
    # Once: the code is gone, and the server has an admin now.
    assert setup(code=code).status_code == 409
    assert _announce() is None


def test_the_setup_code_never_takes_an_account_with_a_password(client):
    _make_user("Hans", role="admin", password=None)
    _make_user("anna")  # a reader who has a password
    code = _announce()
    taken = client.post("/api/auth/setup", json={"username": "anna", "password": PASSWORD, "code": code})
    assert taken.status_code == 409
    fresh = client.post("/api/auth/setup", json={"username": "Ny admin", "password": PASSWORD, "code": code})
    assert fresh.status_code == 201
    assert (fresh.json()["username"], fresh.json()["role"]) == ("Ny admin", "admin")


def test_wrong_setup_codes_are_throttled(client, settings):
    settings(login_max_failures=2)
    _make_user("Hans", role="admin", password=None)
    code = _announce()
    for _ in range(2):
        client.post("/api/auth/setup", json={"username": "Hans", "password": PASSWORD, "code": "AAAA-AAAA"})
    blocked = client.post("/api/auth/setup", json={"username": "Hans", "password": PASSWORD, "code": code})
    assert blocked.status_code == 429


def test_an_admin_who_can_log_in_means_no_setup(client):
    _make_user("Hans", role="admin")
    _make_user("reader", password=None)
    assert client.get("/api/auth/config").json()["setup_required"] is False
    assert _announce() is None
    refused = client.post("/api/auth/setup", json={"username": "x", "password": PASSWORD, "code": "AAAA-AAAA"})
    assert refused.status_code == 409


def test_setup_refuses_a_short_password(client):
    assert client.post("/api/auth/setup", json={"username": "a", "password": "short"}).status_code == 422


def test_password_login_and_logout(client):
    _make_user("anna")
    assert client.get("/api/auth/me").status_code == 401
    assert _login(client, "anna", "wrong password").status_code == 401
    response = _login(client, "ANNA")
    assert response.status_code == 200
    assert response.json()["account"]["csrf_token"] == client.cookies.get("kodex_csrf")
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "samesite=lax" in cookie.lower()
    me = client.get("/api/auth/me").json()
    assert (me["username"], me["auth_method"], me["has_password"]) == ("anna", "session", True)
    assert client.post("/api/auth/logout").status_code == 403  # no CSRF token
    assert client.post("/api/auth/logout", headers=_csrf(client)).status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_unsafe_requests_need_the_csrf_token(client):
    _make_user("anna")
    _login(client, "anna")
    body = {"name": "Läsplatta", "purpose": "opds"}
    assert client.post("/api/me/api-keys", json=body).status_code == 403
    assert client.post("/api/me/api-keys", json=body, headers={"x-csrf-token": "guess"}).status_code == 403
    assert client.post("/api/me/api-keys", json=body, headers=_csrf(client)).status_code == 201


def test_failed_logins_make_the_username_wait(client, settings):
    settings(login_max_failures=3)
    _make_user("anna")
    for _ in range(3):
        assert _login(client, "anna", "wrong password").status_code == 401
    blocked = _login(client, "anna")
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0
    _make_user("bo")
    assert _login(client, "bo").status_code == 200  # others aren't affected


def test_disabled_accounts_cant_log_in_or_stay_in(client):
    user_id = _make_user("anna")
    _login(client, "anna")
    with SessionLocal() as db:
        db.get(User, user_id).disabled = True
        db.commit()
    assert client.get("/api/auth/me").status_code == 401
    assert _login(client, "anna").status_code == 403


def test_changing_the_password_ends_the_other_sessions(client):
    _make_user("anna")
    other = TestClient(app, base_url="https://kodex.test")
    assert _login(other, "anna").status_code == 200
    _login(client, "anna")
    wrong = client.post("/api/auth/password", json={"current_password": "nope", "new_password": "another long one"},
                        headers=_csrf(client))  # fmt: skip
    assert wrong.status_code == 403
    changed = client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "another long one"},
                          headers=_csrf(client))  # fmt: skip
    assert changed.status_code == 204
    assert client.get("/api/auth/me").status_code == 200
    assert other.get("/api/auth/me").status_code == 401
    assert [s["current"] for s in client.get("/api/auth/sessions").json()] == [True]
    assert _login(TestClient(app), "anna", "another long one").status_code == 200


def _new_key(client: TestClient, purpose: str) -> str:
    response = client.post("/api/me/api-keys", json={"name": purpose, "purpose": purpose}, headers=_csrf(client))
    assert response.status_code == 201
    key = response.json()["key"]
    assert key.startswith("kdx_") and response.json()["prefix"] == key[:10]
    return key


def test_api_keys_work_only_for_their_purpose(client):
    _make_user("anna")
    _login(client, "anna")
    app_key, opds_key, kosync_key = (_new_key(client, p) for p in ("app", "opds", "kosync"))
    listed = client.get("/api/me/api-keys").json()
    assert sorted(k["purpose"] for k in listed) == ["app", "kosync", "opds"]
    assert all("key" not in k for k in listed)

    bare = TestClient(app)
    assert bare.get("/api/auth/me", headers={"authorization": f"Bearer {app_key}"}).json()["auth_method"] == "api_key"
    assert bare.get("/api/auth/me", headers={"authorization": f"Bearer {opds_key}"}).status_code == 401
    assert bare.get("/opds", auth=("anything", opds_key)).status_code == 200
    assert bare.get("/opds", auth=("anything", app_key)).status_code == 401
    md5 = hashlib.md5(kosync_key.encode()).hexdigest()
    assert bare.get("/kosync/users/auth", headers={"x-auth-user": "Anna", "x-auth-key": md5}).status_code == 200
    assert bare.get("/kosync/users/auth", headers={"x-auth-user": "bo", "x-auth-key": md5}).status_code == 401

    app_key_id = next(k["id"] for k in listed if k["purpose"] == "app")
    assert client.delete(f"/api/me/api-keys/{app_key_id}", headers=_csrf(client)).status_code == 204
    assert bare.get("/api/auth/me", headers={"authorization": f"Bearer {app_key}"}).status_code == 401


def test_v1_opds_tokens_still_work(client):
    _make_user("anna", opds_token="v1-token")
    assert TestClient(app).get("/opds", auth=("x", "v1-token")).status_code == 200


def test_guests_cant_make_requests(client):
    _make_user("gäst", role="guest")
    _login(client, "gäst")
    response = client.post("/api/requests", json={"title": "En bok", "media_type": "ebook"}, headers=_csrf(client))
    assert response.status_code == 403


def test_admins_manage_users_but_keep_one_admin(client):
    admin_id = _make_user("admin", role="admin")
    _make_user("anna")
    _login(client, "anna")
    assert client.get("/api/admin/users").status_code == 403
    _login(client, "admin")
    created = client.post("/api/admin/users", json={"username": "Bo", "role": "guest", "password": PASSWORD},
                          headers=_csrf(client))  # fmt: skip
    assert created.status_code == 201 and created.json()["role"] == "guest"
    taken = client.post("/api/admin/users", json={"username": "bo"}, headers=_csrf(client))
    assert taken.status_code == 409
    bo_id = created.json()["id"]
    promoted = client.patch(f"/api/admin/users/{bo_id}", json={"role": "admin"}, headers=_csrf(client))
    assert promoted.json()["role"] == "admin"
    disabled = client.patch(f"/api/admin/users/{bo_id}", json={"disabled": True}, headers=_csrf(client))
    assert disabled.json()["disabled"] is True
    last = client.patch(f"/api/admin/users/{admin_id}", json={"role": "user"}, headers=_csrf(client))
    assert last.status_code == 409
    assert [u["username"] for u in client.get("/api/admin/users").json()] == ["admin", "anna", "Bo"]


def test_the_command_line_sets_a_password(client, monkeypatch, capsys):
    from kodex.core.auth import cli

    with SessionLocal() as db:
        db.add(User(username="v1-anna", oidc_subject="sub-anna", role="user"))
        db.commit()
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{PASSWORD}\n"))
    assert cli.main(["set-password", "v1-anna", "--role", "admin", "--password-stdin"]) == 0
    assert "role admin" in capsys.readouterr().out
    assert _login(client, "v1-anna").json()["account"]["role"] == "admin"
    with pytest.raises(SystemExit):
        cli.main(["set-password", "nobody", "--password-stdin"])


def test_auth_disabled_answers_with_the_dev_user(client, settings):
    settings(auth_disabled="true")
    assert client.get("/api/auth/me").json()["auth_method"] == "dev"


class FakeProvider:
    """An OpenID Connect provider on an httpx.MockTransport."""

    def __init__(self) -> None:
        self.key = RSAKey.generate_key(2048, parameters={"kid": "k1"})
        self.claims: dict = {"sub": "sub-anna", "preferred_username": "anna", "groups": ["kodex-users"]}
        self.nonce_override: str | None = None
        self.codes: dict[str, dict] = {}

    def authorize(self, url: str) -> str:
        """What the provider would do after the user logs in: a code for
        the request's nonce and PKCE challenge."""
        params = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        code = f"code-{len(self.codes)}"
        self.codes[code] = params
        return f"/api/auth/oidc/callback?state={params['state']}&code={code}"

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={
                "issuer": _ISSUER, "authorization_endpoint": "https://idp.test/authorize",
                "token_endpoint": "https://idp.test/token", "jwks_uri": "https://idp.test/jwks",
                "userinfo_endpoint": "https://idp.test/userinfo"})  # fmt: skip
        if request.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [self.key.as_dict(private=False)]})
        if request.url.path == "/userinfo":
            return httpx.Response(200, json={"sub": self.claims["sub"], "email": "anna@example.test"})
        if request.url.path == "/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            sent = self.codes.pop(form["code"], None)
            digest = hashlib.sha256(form["code_verifier"].encode()).digest()
            if sent is None or base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != sent["code_challenge"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            now = int(time.time())
            claims = {"iss": _ISSUER, "aud": "kodex-web", "iat": now, "exp": now + 300,
                      "nonce": self.nonce_override or sent["nonce"], **self.claims}  # fmt: skip
            token = jwt.encode({"alg": "RS256", "kid": "k1"}, claims, self.key)
            return httpx.Response(200, json={"id_token": token, "access_token": "at", "token_type": "Bearer"})
        return httpx.Response(404)


@pytest.fixture
def provider(client, settings, monkeypatch):
    settings(oidc_issuer=_ISSUER, oidc_client_id="kodex-web", oidc_required_group="kodex-users",
             oidc_admin_group="kodex-admins")  # fmt: skip
    fake = FakeProvider()
    monkeypatch.setattr(oidc, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(fake.handle)))
    oidc._cache.clear()
    yield fake
    oidc._cache.clear()


def _oidc_login(client: TestClient, provider: FakeProvider, next_path: str = "/serier/1") -> httpx.Response:
    start = client.get("/api/auth/oidc/login", params={"next": next_path}, follow_redirects=False)
    assert start.status_code == 303 and start.headers["location"].startswith("https://idp.test/authorize?")
    params = parse_qs(urlsplit(start.headers["location"]).query)
    assert params["redirect_uri"] == ["https://kodex.test/api/auth/oidc/callback"]
    assert params["code_challenge_method"] == ["S256"]
    return client.get(provider.authorize(start.headers["location"]), follow_redirects=False)


def test_an_openid_connect_login(client, provider):
    assert client.get("/api/auth/config").json()["oidc"] is True
    done = _oidc_login(client, provider)
    assert (done.status_code, done.headers["location"]) == (303, "/serier/1")
    me = client.get("/api/auth/me").json()
    assert (me["username"], me["email"], me["oidc"], me["role"]) == ("anna", "anna@example.test", True, "user")
    with SessionLocal() as db:
        assert db.query(User).filter(User.oidc_subject == "sub-anna").count() == 1


def test_a_v1_user_keeps_their_account_and_admin_comes_from_the_group(client, provider):
    with SessionLocal() as db:
        db.add(User(username="anna", oidc_subject="sub-anna", role="user"))
        db.commit()
    provider.claims["groups"] = ["kodex-users", "kodex-admins"]
    _oidc_login(client, provider)
    assert client.get("/api/auth/me").json()["role"] == "admin"
    with SessionLocal() as db:
        assert db.query(User).count() == 1


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"groups": ["others"]}, "reader app group"),
        ({"nonce": "forged"}, "ID token is not valid"),
    ],
)
def test_openid_connect_logins_that_are_refused(client, provider, change, error):
    if "nonce" in change:
        provider.nonce_override = change["nonce"]
    else:
        provider.claims.update(change)
    done = _oidc_login(client, provider)
    assert done.headers["location"].startswith("/login?error=")
    assert error in parse_qs(urlsplit(done.headers["location"]).query)["error"][0]
    assert client.get("/api/auth/me").status_code == 401


def test_an_openid_connect_state_is_used_once(client, provider):
    start = client.get("/api/auth/oidc/login", follow_redirects=False)
    callback = provider.authorize(start.headers["location"])
    assert client.get(callback, follow_redirects=False).headers["location"] == "/"
    again = client.get(callback, follow_redirects=False)
    assert again.headers["location"].startswith("/login?error=")


def test_the_return_path_stays_on_this_site(client, provider):
    done = _oidc_login(client, provider, next_path="//evil.test/x")
    assert done.headers["location"] == "/"


def test_statistics_take_the_dashboard_key_or_an_admin(client, settings):
    settings(stats_api_key="dashboard-key")
    _make_user("admin", role="admin")
    _make_user("anna")
    bare = TestClient(app)
    assert bare.get("/stats", headers={"x-kodex-api-key": "dashboard-key"}).json()["total_books"] == 0
    assert bare.get("/stats", headers={"x-kodex-api-key": "wrong"}).status_code == 401
    assert bare.get("/stats").status_code == 401
    _login(client, "anna")
    assert client.get("/api/stats").status_code == 403
    _login(client, "admin")
    assert client.get("/api/stats").json()["reading_status"] == {"unread": 0, "in_progress": 0, "finished": 0}


def test_integrations_say_what_is_set_up_without_secrets(client, settings):
    settings(comicvine_api_key="secret-cv", ntfy_url="https://push.example.test/", metron_username="m")
    _make_user("admin", role="admin")
    _login(client, "admin")
    found = {i["key"]: i for i in client.get("/api/admin/integrations").json()}
    assert found["comicvine"]["configured"] is True and found["comicvine"]["env"] == ["COMICVINE_API_KEY"]
    assert (found["ntfy"]["configured"], found["ntfy"]["host"]) == (True, "push.example.test")
    assert found["metron"]["configured"] is False  # no password
    assert "secret-cv" not in client.get("/api/admin/integrations").text
