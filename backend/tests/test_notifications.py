"""Tests for kodex/delivery/notify.py: the best-effort Telegram/Discord
push sent when a new Request is created (see test_requests.py for the API
layer that calls this). httpx.post is monkeypatched throughout — no real
network call is ever made in this suite.
"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.models.enums import RequestMediaType, RequestStatus
from app.models.request import Request
from app.models.series import Series
from kodex.delivery import notify as notify_module
from kodex.delivery.notify import notify_new_release, notify_new_request


def _make_settings(**overrides) -> Settings:
    defaults = dict(database_url="sqlite:///:memory:")
    defaults.update(overrides)
    return Settings(**defaults)


def _make_request(**overrides) -> Request:
    defaults = dict(
        id=1,
        requested_by_user_id=1,
        title="Bloodborne: The Board Game",
        media_type=RequestMediaType.SERIES,
        status=RequestStatus.PENDING,
    )
    defaults.update(overrides)
    return Request(**defaults)


class _FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)  # type: ignore[arg-type]


def test_notify_new_request_is_a_noop_when_nothing_is_configured():
    settings = _make_settings()
    assert notify_new_request(_make_request(), settings=settings) is False


def test_notify_new_request_sends_telegram_when_configured(monkeypatch):
    settings = _make_settings(telegram_bot_token="123:abc", telegram_chat_id="456")
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json, timeout))
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)

    assert notify_new_request(_make_request(), settings=settings) is True
    assert len(calls) == 1
    url, payload, _timeout = calls[0]
    assert url == "https://api.telegram.org/bot123:abc/sendMessage"
    assert payload["chat_id"] == "456"
    assert "Bloodborne: The Board Game" in payload["text"]


def test_notify_new_request_sends_discord_when_configured(monkeypatch):
    settings = _make_settings(discord_webhook_url="https://discord.example/webhook")
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)

    assert notify_new_request(_make_request(), settings=settings) is True
    assert calls == [("https://discord.example/webhook", {"content": calls[0][1]["content"]})]
    assert "Bloodborne" in calls[0][1]["content"]


def test_notify_new_request_sends_to_both_when_both_configured(monkeypatch):
    settings = _make_settings(
        telegram_bot_token="123:abc", telegram_chat_id="456", discord_webhook_url="https://discord.example/webhook"
    )
    urls_called = []
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None: urls_called.append(url) or _FakeResponse())

    assert notify_new_request(_make_request(), settings=settings) is True
    assert set(urls_called) == {"https://api.telegram.org/bot123:abc/sendMessage", "https://discord.example/webhook"}


def test_notify_new_request_includes_external_link_when_present():
    request = _make_request(external_link="https://example.com/some-series")

    message = notify_module._format_message(request)

    assert "https://example.com/some-series" in message


def test_notify_new_request_swallows_telegram_errors_and_still_tries_discord(monkeypatch):
    """A broken Telegram config must not prevent the Discord send (or raise
    at all) — see notify.py's docstring on why a notification failure must
    never propagate back to request creation.
    """
    settings = _make_settings(
        telegram_bot_token="bad-token", telegram_chat_id="456", discord_webhook_url="https://discord.example/webhook"
    )

    def fake_post(url, json=None, timeout=None):
        if "telegram" in url:
            raise httpx.ConnectError("unreachable", request=None)  # type: ignore[arg-type]
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)

    assert notify_new_request(_make_request(), settings=settings) is True


def test_notify_new_request_swallows_error_when_only_target_fails(monkeypatch):
    settings = _make_settings(telegram_bot_token="bad-token", telegram_chat_id="456")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down", request=None)))

    assert notify_new_request(_make_request(), settings=settings) is False


def _make_series(**overrides) -> Series:
    defaults = dict(id=1, title="Absolute Corvid")
    defaults.update(overrides)
    return Series(**defaults)


def test_notify_new_release_is_a_noop_when_nothing_is_configured():
    settings = _make_settings()
    assert notify_new_release(_make_series(), settings=settings) is False


def test_notify_new_release_sends_telegram_when_configured(monkeypatch):
    settings = _make_settings(telegram_bot_token="123:abc", telegram_chat_id="456")
    calls = []
    monkeypatch.setattr(
        httpx, "post", lambda url, json=None, timeout=None: calls.append((url, json)) or _FakeResponse()
    )

    assert notify_new_release(_make_series(), settings=settings) is True
    assert len(calls) == 1
    url, payload = calls[0]
    assert url == "https://api.telegram.org/bot123:abc/sendMessage"
    assert "Absolute Corvid" in payload["text"]


def test_notify_new_release_sends_to_both_when_both_configured(monkeypatch):
    settings = _make_settings(
        telegram_bot_token="123:abc", telegram_chat_id="456", discord_webhook_url="https://discord.example/webhook"
    )
    urls_called = []
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None: urls_called.append(url) or _FakeResponse())

    assert notify_new_release(_make_series(), settings=settings) is True
    assert set(urls_called) == {"https://api.telegram.org/bot123:abc/sendMessage", "https://discord.example/webhook"}


def test_notify_new_release_swallows_telegram_errors_and_still_tries_discord(monkeypatch):
    settings = _make_settings(
        telegram_bot_token="bad-token", telegram_chat_id="456", discord_webhook_url="https://discord.example/webhook"
    )

    def fake_post(url, json=None, timeout=None):
        if "telegram" in url:
            raise httpx.ConnectError("unreachable", request=None)  # type: ignore[arg-type]
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)

    assert notify_new_release(_make_series(), settings=settings) is True
