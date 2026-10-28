"""Tests for app/ai/covers.py — mocks every provider's search() and the
Comic Vine rate limiter, so nothing here makes a real network call. See
app/ai/recommendations.py's own tests (test_ai_recommendations.py) for
how this integrates into a generation batch.
"""

from __future__ import annotations

import httpx
import pytest

import app.ai.covers as covers_module
from app.enrichment.base import Candidate
from app.enrichment.ratelimit import SlidingWindowRateLimiter
from app.models.enums import RequestMediaType


def test_fetch_cover_urls_returns_empty_list_for_empty_input():
    assert covers_module.fetch_cover_urls([], comicvine_api_key="key", google_books_api_key="") == []


def test_fetch_cover_urls_uses_anilist_for_manga(monkeypatch):
    monkeypatch.setattr(
        covers_module.anilist,
        "search",
        lambda query, **kw: [Candidate(external_id="1", title=query, thumbnail_url="http://anilist/x.jpg")],
    )

    result = covers_module.fetch_cover_urls(
        [("Bramble", RequestMediaType.MANGA)], comicvine_api_key="", google_books_api_key=""
    )

    assert result == ["http://anilist/x.jpg"]


def test_fetch_cover_urls_uses_open_library_for_ebook(monkeypatch):
    monkeypatch.setattr(
        covers_module.open_library,
        "search",
        lambda query, **kw: [Candidate(external_id="1", title=query, thumbnail_url="http://ol/x.jpg")],
    )
    monkeypatch.setattr(
        covers_module.google_books, "search", lambda query, api_key="", **kw: pytest.fail("should not be called")
    )

    result = covers_module.fetch_cover_urls(
        [("Some Novel", RequestMediaType.EBOOK)], comicvine_api_key="", google_books_api_key=""
    )

    assert result == ["http://ol/x.jpg"]


def test_fetch_cover_urls_falls_back_to_google_books_when_open_library_empty(monkeypatch):
    monkeypatch.setattr(covers_module.open_library, "search", lambda query, **kw: [])
    monkeypatch.setattr(
        covers_module.google_books,
        "search",
        lambda query, api_key="", **kw: [Candidate(external_id="1", title=query, thumbnail_url="http://gbooks/x.jpg")],
    )

    result = covers_module.fetch_cover_urls(
        [("Some Novel", RequestMediaType.EBOOK)], comicvine_api_key="", google_books_api_key="gbkey"
    )

    assert result == ["http://gbooks/x.jpg"]


def test_fetch_cover_urls_sends_a_user_agent_header(monkeypatch):
    """Regression test for 2026-09-21: Comic Vine 403s any request with no
    (or a default httpx) User-Agent as bot traffic — every comic-guessed
    suggestion's cover was silently None because of this, reported as
    "just placeholder images". app/enrichment/http.py's get_client() sets
    this for the rest of the app's Comic Vine calls; this module's raw
    httpx.get() (see its own docstring for why it can't reuse
    comicvine.py's search()) has to set it itself.
    """

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": []}

    captured_headers = {}

    def _fake_get(url, *, params, headers, timeout):
        captured_headers.update(headers)
        return _FakeResponse()

    monkeypatch.setattr(httpx, "get", _fake_get)

    covers_module.fetch_cover_urls(
        [("Absolute Corvid", RequestMediaType.SERIES)], comicvine_api_key="cvkey", google_books_api_key=""
    )

    assert captured_headers.get("User-Agent")


def test_fetch_cover_urls_uses_comicvine_for_series_or_none(monkeypatch):
    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": [{"image": {"thumb_url": "http://cv/x.jpg"}}]}

    monkeypatch.setattr(httpx, "get", lambda url, *, params, headers, timeout: _FakeResponse())

    result = covers_module.fetch_cover_urls(
        [("Absolute Corvid", RequestMediaType.SERIES), ("Untyped Guess", None)],
        comicvine_api_key="cvkey",
        google_books_api_key="",
    )

    assert result == ["http://cv/x.jpg", "http://cv/x.jpg"]


def test_fetch_cover_urls_skips_comicvine_without_an_api_key():
    result = covers_module.fetch_cover_urls(
        [("Absolute Corvid", RequestMediaType.SERIES)], comicvine_api_key="", google_books_api_key=""
    )
    assert result == [None]


def test_fetch_cover_urls_skips_comicvine_when_rate_limit_exhausted(monkeypatch):
    exhausted_limiter = SlidingWindowRateLimiter(max_calls=0, period_seconds=3600, name="test")
    monkeypatch.setattr(covers_module, "comicvine_limiter", exhausted_limiter)

    result = covers_module.fetch_cover_urls(
        [("Absolute Corvid", RequestMediaType.SERIES)], comicvine_api_key="cvkey", google_books_api_key=""
    )

    assert result == [None]


def test_fetch_cover_urls_returns_none_on_provider_error(monkeypatch):
    def _raise(query, **kw):
        raise httpx.ConnectError("down", request=None)

    monkeypatch.setattr(covers_module.anilist, "search", _raise)

    result = covers_module.fetch_cover_urls(
        [("Bramble", RequestMediaType.MANGA)], comicvine_api_key="", google_books_api_key=""
    )

    assert result == [None]


def test_fetch_cover_urls_returns_none_when_no_candidates_found(monkeypatch):
    monkeypatch.setattr(covers_module.anilist, "search", lambda query, **kw: [])

    result = covers_module.fetch_cover_urls(
        [("Obscure Title", RequestMediaType.MANGA)], comicvine_api_key="", google_books_api_key=""
    )

    assert result == [None]


def test_fetch_cover_urls_preserves_order_for_multiple_suggestions(monkeypatch):
    monkeypatch.setattr(
        covers_module.anilist,
        "search",
        lambda query, **kw: [Candidate(external_id="1", title=query, thumbnail_url=f"http://anilist/{query}.jpg")],
    )

    result = covers_module.fetch_cover_urls(
        [(f"Title {i}", RequestMediaType.MANGA) for i in range(10)], comicvine_api_key="", google_books_api_key=""
    )

    assert result == [f"http://anilist/Title {i}.jpg" for i in range(10)]
