"""Passkeys, two-step login, sign-in links and linking a provider account
(kodex.core.auth, ADR 0020), against a software authenticator and the
fake OpenID Connect provider of test_auth."""

from __future__ import annotations

import datetime as dt
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.user import User
from kodex.core.auth import cli, totp
from kodex.core.auth.models import SignInLink
from tests import test_auth as base
from tests.fake_authenticator import UP, FakeAuthenticator

# The fixtures of test_auth, for these tests too.
settings, client, provider = base.settings, base.client, base.provider
PASSWORD, _csrf, _login, _make_user = base.PASSWORD, base._csrf, base._login, base._make_user


def _post(client: TestClient, path: str, body: dict | None = None):
    return client.post(path, json=body or {}, headers=_csrf(client))


def _logout(client: TestClient) -> None:
    assert _post(client, "/api/auth/logout").status_code == 204


def _turn_on_totp(client: TestClient) -> tuple[str, list[str]]:
    """Two-step login for the logged-in user: its secret and recovery codes.
    The code that turned it on was the current step's; the tests log in with
    the next one (``_next``), which the app shows within 30 seconds."""
    setup = _post(client, "/api/auth/totp").json()
    assert setup["uri"].startswith("otpauth://totp/Kodex:")
    secret = setup["secret"]
    assert _post(client, "/api/auth/totp/confirm", {"code": "000000"}).status_code == 400
    step = _now()
    confirmed = _post(client, "/api/auth/totp/confirm", {"code": totp.code_at(secret, step)})
    assert confirmed.status_code == 200
    _confirmed_steps[secret] = step
    return secret, confirmed.json()["codes"]


_confirmed_steps: dict[str, int] = {}


def _now() -> int:
    return totp.step_at(dt.datetime.now(dt.UTC).timestamp())


def _next(secret: str) -> str:
    return totp.code_at(secret, _confirmed_steps[secret] + 1)


def _add_passkey(client: TestClient, authenticator: FakeAuthenticator, name: str = "Telefonen"):
    ceremony = _post(client, "/api/auth/passkeys/options").json()
    assert ceremony["options"]["authenticatorSelection"]["residentKey"] == "required"
    return _post(client, "/api/auth/passkeys", {"ticket": ceremony["ticket"], "name": name,
                                                "credential": authenticator.create(ceremony["options"])})  # fmt: skip


def _passkey_login(client: TestClient, authenticator: FakeAuthenticator, ticket: str | None = None, **answer):
    ceremony = _post(client, "/api/auth/passkeys/login/options", {"ticket": ticket}).json()
    credential = authenticator.get(ceremony["options"], **answer)
    return _post(client, "/api/auth/passkeys/login", {"ticket": ceremony["ticket"], "credential": credential})


def test_two_step_login_with_the_app(client):
    _make_user("anna")
    _login(client, "anna")
    secret, codes = _turn_on_totp(client)
    assert len(codes) == 10 and len(set(codes)) == 10
    me = client.get("/api/auth/me").json()
    assert (me["two_factor"], me["recovery_codes_left"]) == (True, 10)
    _logout(client)

    started = _login(client, "anna").json()
    assert started["account"] is None and started["second_step"]["methods"] == ["totp", "recovery"]
    assert client.get("/api/auth/me").status_code == 401  # not logged in yet
    ticket = started["second_step"]["ticket"]
    assert _post(client, "/api/auth/login/second-step", {"ticket": ticket, "code": "123456"}).status_code == 401
    # The code that turned it on was used: only a later one works.
    used = totp.code_at(secret, _confirmed_steps[secret])
    assert _post(client, "/api/auth/login/second-step", {"ticket": ticket, "code": used}).status_code == 401
    done = _post(client, "/api/auth/login/second-step", {"ticket": ticket, "code": _next(secret)})
    assert done.status_code == 200 and done.json()["username"] == "anna"
    assert client.get("/api/auth/me").json()["username"] == "anna"
    again = _post(client, "/api/auth/login/second-step", {"ticket": ticket, "code": _next(secret)})
    assert again.status_code == 401  # the ticket is used


def test_a_recovery_code_works_once(client):
    _make_user("anna")
    _login(client, "anna")
    _secret, codes = _turn_on_totp(client)
    _logout(client)
    ticket = _login(client, "anna").json()["second_step"]["ticket"]
    spoken = codes[0].upper().replace("-", " ")  # read aloud from paper
    assert _post(client, "/api/auth/login/second-step", {"ticket": ticket, "code": spoken}).status_code == 200
    assert client.get("/api/auth/me").json()["recovery_codes_left"] == 9
    _logout(client)
    ticket = _login(client, "anna").json()["second_step"]["ticket"]
    assert _post(client, "/api/auth/login/second-step", {"ticket": ticket, "code": codes[0]}).status_code == 401


def test_a_ticket_takes_five_wrong_codes(client):
    _make_user("anna")
    _login(client, "anna")
    secret, _codes = _turn_on_totp(client)
    _logout(client)
    ticket = _login(client, "anna").json()["second_step"]["ticket"]
    for _ in range(5):
        assert _post(client, "/api/auth/login/second-step", {"ticket": ticket, "code": "000000"}).status_code == 401
    right = _post(client, "/api/auth/login/second-step", {"ticket": ticket, "code": _next(secret)})
    assert right.status_code in (401, 429)  # the ticket is gone, and the username waits


def test_turning_it_off_and_new_codes_need_a_code(client):
    _make_user("anna")
    _login(client, "anna")
    secret, codes = _turn_on_totp(client)
    assert _post(client, "/api/auth/totp").status_code == 409
    assert _post(client, "/api/auth/recovery-codes", {"code": "000000"}).status_code == 403
    fresh = _post(client, "/api/auth/recovery-codes", {"code": codes[1]}).json()["codes"]
    assert not set(fresh) & set(codes)
    assert _post(client, "/api/auth/totp/disable", {"code": "000000"}).status_code == 403
    assert _post(client, "/api/auth/totp/disable", {"code": _next(secret)}).status_code == 204
    assert client.get("/api/auth/me").json()["two_factor"] is False
    _logout(client)
    assert _login(client, "anna").json()["account"]["username"] == "anna"


def test_changing_it_needs_the_web_session_not_an_app_key(client):
    _make_user("anna")
    _login(client, "anna")
    key = _post(client, "/api/me/api-keys", {"name": "App", "purpose": "app"}).json()["key"]
    bare = TestClient(app, base_url="https://kodex.test")
    headers = {"authorization": f"Bearer {key}"}
    assert bare.post("/api/auth/totp", headers=headers).status_code == 403
    assert bare.post("/api/auth/passkeys/options", headers=headers).status_code == 403


def test_a_passkey_logs_in_without_a_password(client):
    _make_user("anna")
    _login(client, "anna")
    phone = FakeAuthenticator()
    added = _add_passkey(client, phone)
    assert added.status_code == 201
    assert (added.json()["name"], added.json()["backed_up"]) == ("Telefonen", True)
    assert _add_passkey(client, phone).status_code == 400  # the same one twice
    assert client.get("/api/auth/me").json()["passkeys"] == 1
    _logout(client)

    assert client.get("/api/auth/config").json()["passkeys"] is True
    done = _passkey_login(client, phone)
    assert done.status_code == 200 and done.json()["username"] == "anna"
    listed = client.get("/api/auth/passkeys").json()
    assert listed[0]["last_used_at"] is not None


@pytest.mark.parametrize(
    ("answer", "error"),
    [({"flags": UP}, "User verification is required"), ({"origin": "https://evil.test"}, "origin")],
)
def test_passkey_logins_that_are_refused(client, answer, error):
    _make_user("anna")
    _login(client, "anna")
    phone = FakeAuthenticator()
    _add_passkey(client, phone)
    _logout(client)
    refused = _passkey_login(client, phone, **answer)
    assert refused.status_code == 401 and error in refused.json()["detail"]
    assert client.get("/api/auth/me").status_code == 401


def test_an_unknown_passkey_is_refused(client):
    _make_user("anna")
    assert _passkey_login(client, FakeAuthenticator()).status_code == 401


def test_a_passkey_is_a_second_step_too(client):
    _make_user("anna")
    _login(client, "anna")
    _turn_on_totp(client)
    key = FakeAuthenticator()
    _add_passkey(client, key, "Säkerhetsnyckel")
    _logout(client)
    started = _login(client, "anna").json()["second_step"]
    assert started["methods"] == ["totp", "recovery", "passkey"]
    ceremony = _post(client, "/api/auth/passkeys/login/options", {"ticket": started["ticket"]}).json()
    assert ceremony["ticket"] == started["ticket"] and len(ceremony["options"]["allowCredentials"]) == 1
    # A security key without a PIN is enough after the password.
    credential = key.get(ceremony["options"], flags=UP)
    done = _post(client, "/api/auth/passkeys/login", {"ticket": started["ticket"], "credential": credential})
    assert done.status_code == 200 and done.json()["username"] == "anna"


def test_someone_else_s_passkey_isn_t_a_second_step(client):
    _make_user("anna")
    _make_user("bo")
    _login(client, "bo")
    bos = FakeAuthenticator()
    _add_passkey(client, bos)
    _logout(client)
    _login(client, "anna")
    _turn_on_totp(client)
    _logout(client)
    ticket = _login(client, "anna").json()["second_step"]["ticket"]
    assert _passkey_login(client, bos, ticket=ticket).status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_the_last_way_in_can_t_be_removed(client):
    anna = _make_user("anna")
    _login(client, "anna")
    passkey_id = _add_passkey(client, FakeAuthenticator()).json()["id"]
    renamed = client.patch(f"/api/auth/passkeys/{passkey_id}", json={"name": "Mobil"}, headers=_csrf(client))
    assert renamed.json()["name"] == "Mobil"
    with SessionLocal() as db:  # an account that only ever had this passkey
        db.get(User, anna).password_hash = None
        db.commit()
    assert client.delete(f"/api/auth/passkeys/{passkey_id}", headers=_csrf(client)).status_code == 409
    assert client.get("/api/auth/me").json()["passkeys"] == 1


def test_a_sign_in_link_sets_the_password_once(client):
    with SessionLocal() as db:
        db.add(User(username="v1-anna", oidc_subject="sub-anna", role="user"))
        db.commit()
        anna_id = db.query(User).filter(User.username == "v1-anna").one().id
    _make_user("admin", role="admin")
    _login(client, "admin")
    made = _post(client, f"/api/admin/users/{anna_id}/sign-in-link").json()
    assert made["url"].startswith("https://kodex.test/welcome#")
    token = made["url"].split("#", 1)[1]
    _logout(client)

    assert _post(client, "/api/auth/sign-in-link/check", {"token": token}).json() == {"username": "v1-anna"}
    assert _post(client, "/api/auth/sign-in-link", {"token": token, "password": "short"}).status_code == 422
    used = _post(client, "/api/auth/sign-in-link", {"token": token, "password": PASSWORD})
    assert used.status_code == 200 and used.json()["account"]["username"] == "v1-anna"
    assert client.get("/api/auth/me").json()["has_password"] is True
    assert _post(client, "/api/auth/sign-in-link", {"token": token, "password": PASSWORD}).status_code == 404
    _logout(client)
    assert _login(client, "v1-anna").status_code == 200


def test_an_old_sign_in_link_doesn_t_work(client):
    anna = _make_user("anna", password=None)
    _make_user("admin", role="admin")
    _login(client, "admin")
    first = _post(client, f"/api/admin/users/{anna}/sign-in-link").json()["url"].split("#", 1)[1]
    second = _post(client, f"/api/admin/users/{anna}/sign-in-link").json()["url"].split("#", 1)[1]
    assert _post(client, "/api/auth/sign-in-link/check", {"token": first}).status_code == 404
    with SessionLocal() as db:
        db.query(SignInLink).update({"expires_at": dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)})
        db.commit()
    assert _post(client, "/api/auth/sign-in-link/check", {"token": second}).status_code == 404


def test_a_sign_in_link_still_asks_for_the_second_step(client):
    anna = _make_user("anna")
    _login(client, "anna")
    _turn_on_totp(client)
    _logout(client)
    _make_user("admin", role="admin")
    _login(client, "admin")
    token = _post(client, f"/api/admin/users/{anna}/sign-in-link").json()["url"].split("#", 1)[1]
    _logout(client)
    used = _post(client, "/api/auth/sign-in-link", {"token": token, "password": "a new password here"}).json()
    assert used["account"] is None and used["second_step"]["ticket"]


def test_an_admin_resets_a_lost_phone(client):
    anna = _make_user("anna")
    _login(client, "anna")
    _turn_on_totp(client)
    _add_passkey(client, FakeAuthenticator())
    _logout(client)
    _make_user("admin", role="admin")
    _login(client, "admin")
    users = {u["username"]: u for u in client.get("/api/admin/users").json()}
    assert (users["anna"]["two_factor"], users["anna"]["passkeys"]) == (True, 1)
    reset = _post(client, f"/api/admin/users/{anna}/reset-two-factor").json()
    assert (reset["two_factor"], reset["passkeys"]) == (False, 0)
    _logout(client)
    assert _login(client, "anna").json()["account"]["username"] == "anna"


def test_the_command_line_resets_two_step_login(client, capsys):
    _make_user("anna")
    _login(client, "anna")
    _turn_on_totp(client)
    assert cli.main(["reset-two-factor", "anna"]) == 0
    assert "two-step login off" in capsys.readouterr().out
    assert client.get("/api/auth/me").status_code == 401  # logged out everywhere
    assert _login(client, "anna").json()["account"] is not None


def _link(client: TestClient, provider: base.FakeProvider):
    started = _post(client, "/api/auth/oidc/link")
    assert started.status_code == 200
    return client.get(provider.authorize(started.json()["url"]), follow_redirects=False)


def test_a_kodex_account_is_linked_to_the_provider(client, provider):
    _make_user("anna-lokal")
    _login(client, "anna-lokal")
    done = _link(client, provider)
    assert (done.status_code, done.headers["location"]) == (303, "/settings?linked=1")
    assert client.get("/api/auth/me").json()["oidc"] is True
    _logout(client)
    base._oidc_login(client, provider)
    me = client.get("/api/auth/me").json()
    assert me["username"] == "anna-lokal" and me["email"] == "anna@example.test"
    with SessionLocal() as db:
        assert db.query(User).count() == 1

    assert client.delete("/api/auth/oidc/link", headers=_csrf(client)).status_code == 204
    assert client.get("/api/auth/me").json()["oidc"] is False


def test_a_provider_login_links_to_one_account_only(client, provider):
    with SessionLocal() as db:
        db.add(User(username="anna", oidc_subject="sub-anna", role="user"))
        db.commit()
    _make_user("bo")
    _login(client, "bo")
    done = _link(client, provider)
    assert done.headers["location"].startswith("/settings?link_error=")
    assert "another Kodex account" in parse_qs(urlsplit(done.headers["location"]).query)["link_error"][0]


def test_linking_is_bound_to_the_session_that_started_it(client, provider):
    _make_user("anna")
    _make_user("mallory")
    _login(client, "mallory")
    started = _post(client, "/api/auth/oidc/link").json()["url"]
    callback = provider.authorize(started)
    victim = TestClient(app, base_url="https://kodex.test")
    _login(victim, "anna")
    done = victim.get(callback, follow_redirects=False)
    assert done.headers["location"].startswith("/settings?link_error=")
    assert victim.get("/api/auth/me").json()["oidc"] is False


def test_unlinking_needs_another_way_in(client, provider):
    base._oidc_login(client, provider)
    assert client.delete("/api/auth/oidc/link", headers=_csrf(client)).status_code == 409


def test_without_creating_users_only_linked_accounts_get_in(client, provider, settings):
    settings(oidc_create_users="false")
    done = base._oidc_login(client, provider)
    assert done.headers["location"].startswith("/login?error=")
    assert "No Kodex account" in parse_qs(urlsplit(done.headers["location"]).query)["error"][0]


def test_v1_s_authentik_names_still_work(client, settings, monkeypatch):
    for name in ("OIDC_ISSUER", "OIDC_CLIENT_ID"):
        monkeypatch.delenv(name, raising=False)
    settings(authentik_issuer=base._ISSUER, authentik_client_id="kodex-web")
    assert client.get("/api/auth/config").json()["oidc"] is True


def test_the_command_line_makes_a_sign_in_link(client, settings, capsys):
    settings(public_app_url="https://kodex.test")
    _make_user("v1-anna", password=None)
    assert cli.main(["sign-in-link", "v1-anna"]) == 0
    url = capsys.readouterr().out.splitlines()[0]
    assert url.startswith("https://kodex.test/welcome#")
    token = url.split("#", 1)[1]
    assert _post(client, "/api/auth/sign-in-link/check", {"token": token}).json() == {"username": "v1-anna"}
