"""Tests for app/enrichment/ratelimit.py's SlidingWindowRateLimiter —
acquire() itself is already exercised indirectly by every provider using
it; this focuses on try_acquire(), the non-blocking variant added for
app/ai/covers.py's speculative cover lookups.
"""

from __future__ import annotations

from app.enrichment.ratelimit import SlidingWindowRateLimiter


def test_try_acquire_succeeds_under_the_limit():
    limiter = SlidingWindowRateLimiter(max_calls=2, period_seconds=60)
    assert limiter.try_acquire() is True
    assert limiter.try_acquire() is True


def test_try_acquire_fails_once_the_window_is_full():
    limiter = SlidingWindowRateLimiter(max_calls=1, period_seconds=60)
    assert limiter.try_acquire() is True
    assert limiter.try_acquire() is False


def test_try_acquire_never_blocks_when_exhausted():
    import time

    limiter = SlidingWindowRateLimiter(max_calls=0, period_seconds=3600)
    start = time.monotonic()
    assert limiter.try_acquire() is False
    assert time.monotonic() - start < 0.1
