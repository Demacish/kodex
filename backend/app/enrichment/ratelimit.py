"""Simple in-process sliding-window rate limiter for outbound enrichment
API calls that have a documented quota — Comic Vine
(https://comicvine.gamespot.com/api/ — 200 requests/hour per key) and,
since 2026-09-11, Metron (https://metron.cloud/ — 20 requests/minute
burst; its separate 5,000/day sustained limit isn't enforced here, since
this app's per-arc/per-book call volumes stay well under it in practice).

The worker container runs a single RQ worker process handling one job at a
time (see app/workers/worker.py), so a module-level, lock-protected window
is sufficient — no cross-process coordination needed.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

logger = logging.getLogger(__name__)

# A blocking wait shorter than this is normal spacing between calls near
# the quota edge and not worth a log line; anything longer means a whole
# library-enrichment run can go quiet for tens of minutes waiting for the
# window to free up, which — with no log trace at all — is indistinguishable
# from a hung/crashed worker from the outside. Found 2026-09-11 debugging
# exactly that: a run that looked stuck for 12+ minutes turned out to be
# correctly waiting out Comic Vine's real 200/hour quota after burning
# through it in the first few minutes of a large library run.
_LOG_THRESHOLD_SECONDS = 5.0


class SlidingWindowRateLimiter:
    """Blocks (sleeps) inside acquire() rather than raising, since enrichment
    is a background task with no end user waiting on it synchronously —
    throttling to stay under quota is preferable to failing the job.
    """

    def __init__(self, max_calls: int, period_seconds: float, name: str = "provider") -> None:
        self._max_calls = max_calls
        self._period_seconds = period_seconds
        self._name = name
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= self._period_seconds:
                    self._calls.popleft()
                if len(self._calls) < self._max_calls:
                    self._calls.append(now)
                    return
                sleep_for = self._period_seconds - (now - self._calls[0])
            if sleep_for >= _LOG_THRESHOLD_SECONDS:
                logger.info(
                    "%s rate limit reached (%d calls/%.0fs) — sleeping %.0fs before the next call",
                    self._name,
                    self._max_calls,
                    self._period_seconds,
                    sleep_for,
                )
            time.sleep(max(sleep_for, 0.05))

    def try_acquire(self) -> bool:
        """Non-blocking sibling of acquire() — for a caller that would
        rather skip the call entirely than wait out the window (see
        app/ai/covers.py: a speculative cover lookup running inside a
        synchronous, user-facing request, where acquire()'s normal
        "sleep until quota frees up" behavior would hang that request
        instead of the background job it's designed for).
        """
        with self._lock:
            now = time.monotonic()
            while self._calls and now - self._calls[0] >= self._period_seconds:
                self._calls.popleft()
            if len(self._calls) < self._max_calls:
                self._calls.append(now)
                return True
            return False


# Comic Vine's documented limit is 200 requests/hour per API key.
comicvine_limiter = SlidingWindowRateLimiter(max_calls=200, period_seconds=3600, name="Comic Vine")

# Metron's documented BURST limit (the one actually worth enforcing here —
# see this module's docstring for why the daily one isn't).
metron_limiter = SlidingWindowRateLimiter(max_calls=20, period_seconds=60, name="Metron")
