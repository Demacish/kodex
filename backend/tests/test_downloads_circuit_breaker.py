from __future__ import annotations

import time

from kodex.acquire.clients.circuit_breaker import CircuitBreaker


def test_starts_closed():
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    assert breaker.is_open is False


def test_opens_after_threshold_consecutive_failures():
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.is_open is False
    breaker.record_failure()
    assert breaker.is_open is True


def test_success_resets_failure_count():
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.is_open is False


def test_closes_again_after_cooldown_elapses():
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.05)
    breaker.record_failure()
    assert breaker.is_open is True
    time.sleep(0.06)
    assert breaker.is_open is False
