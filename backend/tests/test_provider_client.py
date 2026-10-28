"""kodex.matching.providers.base: cache, database rate limiting, retries,
and the recording and replay transports. No network: every request is
answered by a handler or a stored record."""

from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest
from sqlalchemy import text

from kodex.matching.providers.base import (
    ClientSettings,
    NotConfigured,
    NotFound,
    ProviderClient,
    ProviderError,
    RateLimited,
    RateLimiter,
    RatePolicy,
    RecordingTransport,
    ReplayTransport,
)
from tests.db import fresh_engine


class FakeClock:
    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.now = start
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(round(seconds, 3))
        self.now += seconds


class Toy(ProviderClient):
    name = "toy"
    base_url = "https://toy.example/api/"
    secret_params = frozenset({"key"})
    default_policy = RatePolicy(min_interval=1.0)
    bucket_policies = {"search": RatePolicy(min_interval=0, window=3600, window_limit=2)}

    def auth_params(self) -> dict[str, str]:
        return {"key": "s3cret"}


@pytest.fixture
def engine():
    return fresh_engine()


def _client(engine, handler, clock=None, **settings):
    clock = clock or FakeClock()
    transport = handler if isinstance(handler, httpx.BaseTransport) else httpx.MockTransport(handler)
    return Toy(
        engine=engine,
        settings=ClientSettings(user_agent="kodex-tests", backoff=1.0, **settings),
        transport=transport,
        sleep=clock.sleep,
        clock=clock,
    ), clock


def test_responses_are_cached_without_credentials(engine):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"hits": [1]})

    client, clock = _client(engine, handler)
    assert client.get("items", {"q": "x"}) == {"hits": [1]}
    assert client.get("items", {"q": "x"}) == {"hits": [1]}
    assert len(calls) == 1
    assert calls[0].url.params["key"] == "s3cret"
    assert calls[0].headers["user-agent"] == "kodex-tests"
    with engine.connect() as connection:
        stored = connection.execute(text("SELECT request::text FROM provider_cache")).scalar_one()
    assert "s3cret" not in stored

    clock.now += dt.timedelta(days=8).total_seconds()  # past the 7-day search lifetime
    client.get("items", {"q": "x"})
    assert len(calls) == 2


def test_id_lookups_live_longer_in_the_cache(engine):
    calls = []
    client, clock = _client(engine, lambda request: calls.append(1) or httpx.Response(200, json={}))
    client.get("item/1", lookup=True)
    clock.now += dt.timedelta(days=20).total_seconds()
    client.get("item/1", lookup=True)
    assert len(calls) == 1


def test_min_interval_spaces_calls_out(engine):
    client, clock = _client(engine, lambda request: httpx.Response(200, json={}))
    client.get("a")
    client.get("b")
    client.get("c")
    assert clock.slept == [1.0, 1.0]


def test_window_budget_runs_out(engine):
    client, clock = _client(engine, lambda request: httpx.Response(200, json={}))
    client.get("a", bucket="search")
    client.get("b", bucket="search")
    with pytest.raises(RateLimited) as excinfo:
        client.get("c", bucket="search")
    assert excinfo.value.retry_at.timestamp() == pytest.approx(clock.now - 1.0 + 3600, abs=2)
    clock.now += 3601
    client.get("c", bucket="search")


def test_budget_is_shared_between_clients(engine):
    first, clock = _client(engine, lambda request: httpx.Response(200, json={}))
    second, _ = _client(engine, lambda request: httpx.Response(200, json={}), clock=clock)
    first.get("a", bucket="search")
    second.get("b", bucket="search")
    with pytest.raises(RateLimited):
        first.get("c", bucket="search")


def test_429_with_retry_after_waits_and_retries(engine):
    responses = iter([httpx.Response(429, headers={"Retry-After": "5"}), httpx.Response(200, json={"ok": True})])
    client, clock = _client(engine, lambda request: next(responses))
    assert client.get("a") == {"ok": True}
    assert 5.0 in clock.slept


def test_long_retry_after_raises_rate_limited(engine):
    client, _ = _client(engine, lambda request: httpx.Response(429, headers={"Retry-After": "7200"}))
    with pytest.raises(RateLimited):
        client.get("a")


def test_exhausted_header_budget_holds_further_calls(engine):
    def handler(request):
        return httpx.Response(200, json={}, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "30"})

    client, clock = _client(engine, handler)
    client.get("a")
    client.get("b")
    assert clock.slept[-1] == pytest.approx(30.0, abs=1.01)


def test_server_errors_are_retried_with_backoff(engine):
    responses = iter([httpx.Response(503), httpx.Response(502), httpx.Response(200, json={"ok": 1})])
    client, clock = _client(engine, lambda request: next(responses))
    assert client.get("a") == {"ok": 1}
    assert clock.slept[:2] == [1.0, 2.0] or 2.0 in clock.slept


def test_persistent_failures_raise(engine):
    client, _ = _client(engine, lambda request: httpx.Response(500))
    with pytest.raises(ProviderError):
        client.get("a")


@pytest.mark.parametrize(
    ("status", "error"), [(404, NotFound), (401, NotConfigured), (403, NotConfigured), (400, ProviderError)]
)
def test_client_errors(engine, status, error):
    client, _ = _client(engine, lambda request: httpx.Response(status, json={}))
    with pytest.raises(error):
        client.get("a")


def test_failed_calls_are_not_cached(engine):
    responses = iter(
        [httpx.Response(500), httpx.Response(500), httpx.Response(500), httpx.Response(200, json={"n": 1})]
    )
    client, _ = _client(engine, lambda request: next(responses))
    with pytest.raises(ProviderError):
        client.get("a")
    assert client.get("a") == {"n": 1}


def test_recording_transport_writes_responses_without_secrets(engine, tmp_path):
    inner = httpx.MockTransport(lambda request: httpx.Response(200, json={"name": "The Crimson Harbor"}))
    client, _ = _client(engine, RecordingTransport(tmp_path, {"key"}, inner=inner))
    client.get("items", {"q": "harbor"})
    (record_file,) = tmp_path.glob("*.json")
    record = json.loads(record_file.read_text())
    assert record["request"] == {
        "method": "GET",
        "url": "https://toy.example/api/items",
        "params": {"q": "harbor"},
        "body": None,
    }
    assert record["response"]["body"] == {"name": "The Crimson Harbor"}
    assert "s3cret" not in record_file.read_text()

    replay = ReplayTransport.from_directory(tmp_path, {"key"})
    fresh = fresh_engine()
    replayed, _ = _client(fresh, replay)
    assert replayed.get("items", {"q": "harbor"}) == {"name": "The Crimson Harbor"}


def test_replay_transport_refuses_unknown_requests(engine):
    client, _ = _client(engine, ReplayTransport([], {"key"}))
    with pytest.raises(ProviderError, match="No stored response"):
        client.get("items", {"q": "missing"})


def test_limiter_never_sleeps_beyond_max_wait(engine):
    clock = FakeClock()
    limiter = RateLimiter(engine, clock=clock, sleep=clock.sleep, max_wait=10)
    limiter.hold("toy", "default", clock.now + 100)
    with pytest.raises(RateLimited):
        limiter.acquire("toy", [("default", RatePolicy(min_interval=1))])
