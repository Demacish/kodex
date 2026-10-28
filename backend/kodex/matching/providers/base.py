"""The shared provider client: every metadata provider (Comic Vine, Metron,
MangaDex, ...) talks HTTP through :class:`ProviderClient`, which adds

- a response cache in the database (``ProviderCache``), keyed on the
  request without credentials, with separate lifetimes for searches and
  id lookups;
- rate limiting stored in the database (``ProviderRateState``), so every
  worker shares one budget: a minimum interval between calls and optional
  fixed windows (Comic Vine allows 200 calls per resource and hour), both
  corrected by the provider's own ``Retry-After`` and ``X-RateLimit-*``
  headers;
- retries with backoff on 5xx, timeouts and 429.

Transports decide where requests go: the real network, a recorder that
also writes each response to a directory, or a replayer that serves
stored responses and fails on anything else (tests never touch the
network).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    """A provider call failed in a way worth reporting."""


class NotConfigured(ProviderError):
    """The provider needs credentials that aren't set."""


class RateLimited(ProviderError):
    """The budget is used up until ``retry_at``; try again later."""

    def __init__(self, provider: str, retry_at: dt.datetime) -> None:
        super().__init__(f"{provider} rate limit reached until {retry_at.isoformat()}")
        self.provider = provider
        self.retry_at = retry_at


class NotFound(ProviderError):
    pass


# --- Provider-neutral results -------------------------------------------------


@dataclass
class RunCandidate:
    """A series at a provider (a Comic Vine volume, a Metron series, a
    MangaDex manga, ...)."""

    provider: str
    id: str
    name: str
    start_year: int | None = None
    end_year: int | None = None
    publisher: str | None = None
    issue_count: int | None = None
    aliases: list[str] = field(default_factory=list)
    cover_url: str | None = None
    cover_hash: str | None = None
    # issue | collected | one_shot | annual | manga | novel | ...
    format: str | None = None
    volume: str | None = None
    country: str | None = None
    language: str | None = None
    status: str | None = None
    summary: str | None = None
    url: str | None = None
    # The same series at other providers: {"comicvine": "42721", "mal": "13"}.
    links: dict[str, str] = field(default_factory=dict)


@dataclass
class IssueRef:
    """One issue (or chapter/volume) of a run."""

    provider: str
    id: str
    run_id: str
    number: str | None
    name: str | None = None
    year: int | None = None
    cover_date: str | None = None
    cover_url: str | None = None
    cover_hash: str | None = None
    page_count: int | None = None
    links: dict[str, str] = field(default_factory=dict)
    volume: str | None = None  # the volume a chapter is collected in


@dataclass
class BookRef:
    """An e-book work or edition."""

    provider: str
    id: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    publisher: str | None = None
    isbn13: list[str] = field(default_factory=list)
    page_count: int | None = None
    series: str | None = None
    series_index: str | None = None
    work_id: str | None = None
    cover_url: str | None = None
    language: str | None = None
    summary: str | None = None


# --- Rate limiting ------------------------------------------------------------


@dataclass(frozen=True)
class RatePolicy:
    """``min_interval`` seconds between calls; optionally at most
    ``window_limit`` calls per ``window`` seconds."""

    min_interval: float = 1.0
    window: float | None = None
    window_limit: int | None = None


Clock = Callable[[], float]
Sleep = Callable[[float], None]


def _ts(seconds: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(seconds, dt.UTC)


class RateLimiter:
    """Database-backed limiter shared by every process. ``max_wait`` is the
    longest a caller sleeps; beyond that it raises :class:`RateLimited`."""

    def __init__(self, engine: Engine, *, clock: Clock = time.time, sleep: Sleep = time.sleep, max_wait: float = 60.0):
        self.engine = engine
        self.clock = clock
        self.sleep = sleep
        self.max_wait = max_wait

    def acquire(self, provider: str, buckets: Iterable[tuple[str, RatePolicy]]) -> None:
        wait = 0.0
        with self.engine.begin() as connection:
            for bucket, policy in buckets:
                wait = max(wait, self._reserve(connection, provider, bucket, policy))
        if wait > 0:
            self.sleep(wait)

    def _reserve(self, connection: Any, provider: str, bucket: str, policy: RatePolicy) -> float:
        connection.execute(
            text(
                "INSERT INTO provider_rate_state (provider, bucket) VALUES (:p, :b) ON CONFLICT (provider, bucket) DO NOTHING"
            ),
            {"p": provider, "b": bucket},
        )
        row = connection.execute(
            text(
                'SELECT "limit", remaining, reset_at, next_allowed_at FROM provider_rate_state '
                "WHERE provider = :p AND bucket = :b FOR UPDATE"
            ),
            {"p": provider, "b": bucket},
        ).one()
        now = self.clock()
        limit, remaining = row.limit, row.remaining
        reset_at = row.reset_at.timestamp() if row.reset_at else None
        if policy.window and policy.window_limit:
            if reset_at is None or reset_at <= now:
                limit, remaining, reset_at = policy.window_limit, policy.window_limit, now + policy.window
            if remaining is not None and remaining <= 0:
                raise RateLimited(provider, _ts(reset_at))
            remaining = (remaining if remaining is not None else policy.window_limit) - 1
        elif reset_at is not None and reset_at <= now:
            remaining = None  # a header-reported window has passed
        next_allowed = row.next_allowed_at.timestamp() if row.next_allowed_at else now
        start = max(now, next_allowed)
        wait = start - now
        if wait > self.max_wait:
            raise RateLimited(provider, _ts(start))
        connection.execute(
            text(
                'UPDATE provider_rate_state SET "limit" = :limit, remaining = :remaining, reset_at = :reset_at, '
                "next_allowed_at = :next, updated_at = now() WHERE provider = :p AND bucket = :b"
            ),
            {
                "limit": limit,
                "remaining": remaining,
                "reset_at": _ts(reset_at) if reset_at else None,
                "next": _ts(start + policy.min_interval),
                "p": provider,
                "b": bucket,
            },
        )
        return wait

    def hold(self, provider: str, bucket: str, until: float) -> None:
        """No calls before ``until`` (from ``Retry-After`` or an exhausted
        ``X-RateLimit-Remaining``)."""
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO provider_rate_state (provider, bucket, next_allowed_at) VALUES (:p, :b, :t) "
                    "ON CONFLICT (provider, bucket) DO UPDATE SET next_allowed_at = GREATEST("
                    "COALESCE(provider_rate_state.next_allowed_at, :t), :t), updated_at = now()"
                ),
                {"p": provider, "b": bucket, "t": _ts(until)},
            )


# --- Transports ---------------------------------------------------------------


def request_key(method: str, url: str, params: dict[str, Any], body: Any, secret_params: Iterable[str] = ()) -> str:
    """A stable hash of a request without its credentials."""
    clean = {k: v for k, v in sorted(params.items()) if k not in set(secret_params)}
    payload = json.dumps([method.upper(), url, clean, body], sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


class RecordingTransport(httpx.BaseTransport):
    """Sends requests to the network and writes every response to
    ``directory`` (outside the repository: recorded responses are never
    committed, see docs/testing.md)."""

    def __init__(self, directory: Path, secret_params: Iterable[str] = (), inner: httpx.BaseTransport | None = None):
        self.directory = directory
        self.secret_params = set(secret_params)
        self.inner = inner or httpx.HTTPTransport(retries=0)
        directory.mkdir(parents=True, exist_ok=True)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request.read()
        response = self.inner.handle_request(request)
        response.read()
        params = dict(request.url.params)
        body = json.loads(request.content) if request.content else None
        url = str(request.url.copy_with(query=None))
        key = request_key(request.method, url, params, body, self.secret_params)
        try:
            content: Any = response.json()
        except ValueError:
            content = response.text
        record = {
            "request": {
                "method": request.method,
                "url": url,
                "params": {k: v for k, v in params.items() if k not in self.secret_params},
                "body": body,
            },
            "response": {
                "status": response.status_code,
                "headers": {
                    k: v
                    for k, v in response.headers.items()
                    if k.lower().startswith(("x-ratelimit", "retry-after", "content-type"))
                },
                "body": content,
            },
        }
        (self.directory / f"{key}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1))
        return response


class ReplayTransport(httpx.BaseTransport):
    """Serves responses from JSON records (as RecordingTransport writes
    them, or written by hand). An unknown request is an error, never a
    network call."""

    def __init__(self, records: Iterable[dict[str, Any]], secret_params: Iterable[str] = ()):
        self.secret_params = set(secret_params)
        self.responses: dict[str, dict[str, Any]] = {}
        self.calls: list[str] = []
        for record in records:
            req = record["request"]
            key = request_key(req["method"], req["url"], req.get("params") or {}, req.get("body"), self.secret_params)
            self.responses[key] = record["response"]

    @classmethod
    def from_directory(cls, directory: Path, secret_params: Iterable[str] = ()) -> ReplayTransport:
        records = [json.loads(path.read_text()) for path in sorted(directory.rglob("*.json"))]
        return cls(records, secret_params)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request.read()
        params = dict(request.url.params)
        body = json.loads(request.content) if request.content else None
        url = str(request.url.copy_with(query=None))
        key = request_key(request.method, url, params, body, self.secret_params)
        self.calls.append(f"{request.method} {url} {params}")
        stored = self.responses.get(key)
        if stored is None:
            clean = {k: v for k, v in params.items() if k not in self.secret_params}
            raise ProviderError(f"No stored response for {request.method} {url} {clean} {body or ''}")
        body_out = stored["body"]
        content = json.dumps(body_out).encode() if not isinstance(body_out, str) else body_out.encode()
        headers = {"content-type": "application/json", **(stored.get("headers") or {})}
        return httpx.Response(stored["status"], headers=headers, content=content, request=request)


# --- The client ---------------------------------------------------------------


@dataclass(frozen=True)
class ClientSettings:
    user_agent: str
    timeout: float = 15.0
    search_ttl: dt.timedelta = dt.timedelta(days=7)
    id_ttl: dt.timedelta = dt.timedelta(days=30)
    max_attempts: int = 3
    backoff: float = 1.0


class ProviderClient:
    """HTTP with cache, rate limits and retries for one provider.
    Subclasses set ``name``, ``base_url``, ``secret_params`` and the rate
    policies per bucket."""

    name: str = ""
    base_url: str = ""
    secret_params: frozenset[str] = frozenset()
    default_policy: RatePolicy = RatePolicy()
    bucket_policies: dict[str, RatePolicy] = {}

    def __init__(
        self,
        *,
        engine: Engine,
        settings: ClientSettings,
        transport: httpx.BaseTransport | None = None,
        limiter: RateLimiter | None = None,
        sleep: Sleep = time.sleep,
        clock: Clock = time.time,
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.limiter = limiter or RateLimiter(engine, clock=clock, sleep=sleep)
        self.sleep = sleep
        self.clock = clock
        self.http = httpx.Client(
            base_url=self.base_url,
            transport=transport,
            timeout=settings.timeout,
            headers={"User-Agent": settings.user_agent, "Accept": "application/json", **self.extra_headers()},
            auth=self.http_auth(),
            follow_redirects=True,
        )

    def extra_headers(self) -> dict[str, str]:
        return {}

    def http_auth(self) -> httpx.Auth | None:
        return None

    def auth_params(self) -> dict[str, str]:
        """Credentials sent as query parameters (left out of cache keys)."""
        return {}

    # Responses that are errors even with a 200 status (Comic Vine).
    def check_payload(self, payload: Any) -> None:
        return None

    def get(
        self, path: str, params: dict[str, Any] | None = None, *, bucket: str = "default", lookup: bool = False
    ) -> Any:
        return self._request("GET", path, params or {}, None, bucket=bucket, lookup=lookup)

    def post(self, path: str, body: Any, *, bucket: str = "default", lookup: bool = False) -> Any:
        return self._request("POST", path, {}, body, bucket=bucket, lookup=lookup)

    def _request(self, method: str, path: str, params: dict[str, Any], body: Any, *, bucket: str, lookup: bool) -> Any:
        url = str(self.http.build_request(method, path).url.copy_with(query=None))
        key = request_key(method, url, params, body, self.secret_params)
        cached = self._cached(key)
        if cached is not None:
            return cached
        payload = self._fetch(method, path, params, body, bucket)
        ttl = self.settings.id_ttl if lookup else self.settings.search_ttl
        self._store(key, method, url, params, body, payload, ttl)
        return payload

    def _cached(self, key: str) -> Any:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT payload FROM provider_cache WHERE provider = :p AND query_hash = :k AND expires_at > :now"
                ),
                {"p": self.name, "k": key, "now": _ts(self.clock())},
            ).first()
        return row.payload if row is not None else None

    def _store(
        self, key: str, method: str, url: str, params: dict[str, Any], body: Any, payload: Any, ttl: dt.timedelta
    ) -> None:
        clean = {k: v for k, v in params.items() if k not in self.secret_params}
        now = _ts(self.clock())
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO provider_cache (provider, query_hash, request, status, payload, fetched_at, expires_at) "
                    "VALUES (:p, :k, CAST(:req AS json), 200, CAST(:payload AS json), :now, :exp) "
                    "ON CONFLICT (provider, query_hash) DO UPDATE SET payload = EXCLUDED.payload, "
                    "fetched_at = EXCLUDED.fetched_at, expires_at = EXCLUDED.expires_at"
                ),
                {
                    "p": self.name,
                    "k": key,
                    "req": json.dumps({"method": method, "url": url, "params": clean, "body": body}, default=str),
                    "payload": json.dumps(payload),
                    "now": now,
                    "exp": now + ttl,
                },
            )

    def _buckets(self, bucket: str) -> list[tuple[str, RatePolicy]]:
        buckets = [("default", self.default_policy)]
        if bucket != "default":
            buckets.append((bucket, self.bucket_policies.get(bucket, RatePolicy(min_interval=0))))
        return buckets

    def _fetch(self, method: str, path: str, params: dict[str, Any], body: Any, bucket: str) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.settings.max_attempts):
            self.limiter.acquire(self.name, self._buckets(bucket))
            try:
                response = self.http.request(method, path, params={**params, **self.auth_params()}, json=body)
            except httpx.TransportError as exc:
                last_error = exc
                self.sleep(self.settings.backoff * 2**attempt)
                continue
            self._observe_headers(response, bucket)
            if response.status_code == 429:
                retry_after = _retry_after(response, self.clock())
                self.limiter.hold(self.name, bucket, self.clock() + retry_after)
                if retry_after > self.limiter.max_wait:
                    raise RateLimited(self.name, _ts(self.clock() + retry_after))
                last_error = ProviderError(f"{self.name}: 429 Too Many Requests")
                continue
            if response.status_code >= 500:
                last_error = ProviderError(f"{self.name}: HTTP {response.status_code}")
                self.sleep(self.settings.backoff * 2**attempt)
                continue
            if response.status_code == 404:
                raise NotFound(f"{self.name}: {method} {path} not found")
            if response.status_code in (401, 403):
                raise NotConfigured(f"{self.name}: HTTP {response.status_code}, check the credentials")
            if response.status_code >= 400:
                raise ProviderError(f"{self.name}: HTTP {response.status_code}: {response.text[:200]}")
            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderError(f"{self.name}: response is not JSON") from exc
            self.check_payload(payload)
            return payload
        raise ProviderError(
            f"{self.name}: {method} {path} failed after {self.settings.max_attempts} attempts: {last_error}"
        )

    def _observe_headers(self, response: httpx.Response, bucket: str) -> None:
        remaining = response.headers.get("x-ratelimit-remaining")
        if remaining is not None and remaining.strip().isdigit() and int(remaining) <= 0:
            reset = response.headers.get("x-ratelimit-reset") or response.headers.get("x-ratelimit-retry-after")
            until = self.clock() + 60
            if reset and reset.strip().replace(".", "", 1).isdigit():
                value = float(reset)
                # Some providers send an epoch time, others seconds to wait.
                until = value if value > 1e9 else self.clock() + value
            self.limiter.hold(self.name, bucket, until)

    def close(self) -> None:
        self.http.close()


def _retry_after(response: httpx.Response, now: float) -> float:
    value = response.headers.get("retry-after") or response.headers.get("x-ratelimit-retry-after")
    if value and value.strip().replace(".", "", 1).isdigit():
        seconds = float(value)
        return seconds - now if seconds > 1e9 else seconds
    return 60.0
