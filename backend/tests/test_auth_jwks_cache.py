"""Tests for app/auth.py's _JWKSCache — the lock added 2026-09-21 to stop
concurrent requests (the homepage alone fires 7 backendFetch calls, each
depending on get_current_user) from each independently re-fetching
Authentik's discovery/JWKS documents on every cache miss/expiry. See the
class's own docstring for the full story.
"""

from __future__ import annotations

import threading
import time

from app.auth import _JWKSCache


class _FakeResponse:
    def __init__(self, json_data: dict) -> None:
        self._json_data = json_data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._json_data


def test_concurrent_callers_on_a_cold_cache_only_fetch_once(monkeypatch):
    cache = _JWKSCache()
    call_count = 0
    call_count_lock = threading.Lock()

    def _fake_get(url, *, timeout):
        nonlocal call_count
        with call_count_lock:
            call_count += 1
        time.sleep(0.05)  # widen the race window so concurrent callers actually overlap
        if "well-known" in url:
            return _FakeResponse({"jwks_uri": "https://issuer.example/jwks"})
        return _FakeResponse({"keys": ["fake-key"]})

    import app.auth as auth_module

    monkeypatch.setattr(auth_module.httpx, "get", _fake_get)

    results = []
    threads = [threading.Thread(target=lambda: results.append(cache.get("https://issuer.example"))) for _ in range(7)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Each real fetch is 2 calls (discovery + jwks) — exactly one
    # successful fetch means call_count == 2, not up to 14 for 7
    # concurrent callers racing an unlocked cache.
    assert call_count == 2
    assert all(r == {"keys": ["fake-key"]} for r in results)


def test_cached_result_is_reused_without_refetching(monkeypatch):
    cache = _JWKSCache()
    call_count = 0

    def _fake_get(url, *, timeout):
        nonlocal call_count
        call_count += 1
        if "well-known" in url:
            return _FakeResponse({"jwks_uri": "https://issuer.example/jwks"})
        return _FakeResponse({"keys": ["fake-key"]})

    import app.auth as auth_module

    monkeypatch.setattr(auth_module.httpx, "get", _fake_get)

    first = cache.get("https://issuer.example")
    second = cache.get("https://issuer.example")

    assert first == second == {"keys": ["fake-key"]}
    assert call_count == 2  # one discovery + one jwks call, not four
