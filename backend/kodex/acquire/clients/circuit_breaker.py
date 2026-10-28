"""A tiny in-process circuit breaker — used by kodex/acquire/clients/scrapers/
getcomics.py to stop hammering a FlareSolverr instance that's already
failing repeatedly (each failed solve costs several seconds of headless
Chromium time on the FlareSolverr side). Per-process state only, not
shared across worker/api processes or persisted — resets on restart,
which is fine for this use: it only needs to survive a single burst of
failures, not remember them forever.
"""

from __future__ import annotations

import time


class CircuitBreaker:
    def __init__(self, *, failure_threshold: int = 3, cooldown_seconds: float = 300.0) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self._cooldown_seconds:
            # Cooldown elapsed — half-open: let the next call through to
            # test the waters, but stay "open" (still counting as failed)
            # until that call explicitly reports success or failure.
            return False
        return True

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            self._opened_at = time.monotonic()
