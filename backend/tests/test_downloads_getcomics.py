"""Tests for kodex/acquire/clients/scrapers/getcomics.py. Mocks
FlareSolverrClient.solve entirely — this module's own client tests
already cover FlareSolverr's request/response shape (test_downloads_
flaresolverr.py), this file only tests search()'s own logic: circuit
breaker wiring + HTML result parsing.
"""

from __future__ import annotations

import pytest

import kodex.acquire.clients.scrapers.getcomics as getcomics_module
from kodex.acquire.clients.base import DownloadClientError
from kodex.acquire.clients.circuit_breaker import CircuitBreaker

_SAMPLE_HTML = """
<h1><a class="download-link" href="http://cdn.example/batman-001.cbz">Absolute Corvid 001 (2026)</a></h1>
<h1><a class="download-link" href="http://cdn.example/batman-002.cbz">Absolute Corvid 002 (2026)</a></h1>
"""


def test_search_returns_parsed_results(monkeypatch):
    monkeypatch.setattr(getcomics_module.FlareSolverrClient, "solve", lambda self, url: _SAMPLE_HTML)
    monkeypatch.setattr(getcomics_module.FlareSolverrClient, "close", lambda self: None)
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)

    results = getcomics_module.search("Absolute Corvid", flaresolverr_url="http://flaresolverr:8191", breaker=breaker)

    assert len(results) == 2
    assert results[0].title == "Absolute Corvid 001 (2026)"
    assert results[0].download_url == "http://cdn.example/batman-001.cbz"


def test_search_raises_when_flaresolverr_not_configured():
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    with pytest.raises(DownloadClientError):
        getcomics_module.search("query", flaresolverr_url="", breaker=breaker)


def test_search_records_failure_and_reraises_on_solve_error(monkeypatch):
    def _raise(self, url):
        raise DownloadClientError("solve failed")

    monkeypatch.setattr(getcomics_module.FlareSolverrClient, "solve", _raise)
    monkeypatch.setattr(getcomics_module.FlareSolverrClient, "close", lambda self: None)
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)

    with pytest.raises(DownloadClientError):
        getcomics_module.search("query", flaresolverr_url="http://flaresolverr:8191", breaker=breaker)

    assert breaker._consecutive_failures == 1


def test_search_short_circuits_when_breaker_is_open(monkeypatch):
    called = False

    def _solve(self, url):
        nonlocal called
        called = True
        return _SAMPLE_HTML

    monkeypatch.setattr(getcomics_module.FlareSolverrClient, "solve", _solve)
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=300)
    breaker.record_failure()  # opens immediately (threshold=1)

    with pytest.raises(DownloadClientError):
        getcomics_module.search("query", flaresolverr_url="http://flaresolverr:8191", breaker=breaker)

    assert called is False


def test_search_records_success_on_success(monkeypatch):
    monkeypatch.setattr(getcomics_module.FlareSolverrClient, "solve", lambda self, url: _SAMPLE_HTML)
    monkeypatch.setattr(getcomics_module.FlareSolverrClient, "close", lambda self: None)
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    breaker.record_failure()

    getcomics_module.search("query", flaresolverr_url="http://flaresolverr:8191", breaker=breaker)

    assert breaker._consecutive_failures == 0
