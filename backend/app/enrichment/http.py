"""A shared httpx client factory for enrichment providers.

Every provider function takes an optional `client` parameter (defaulting to
`get_client()`) instead of importing httpx directly — that's what lets the
test suite pass in a fake client without needing to monkeypatch httpx
itself. Real network access to these APIs has NOT been exercised from the
environment this code was written in (its outbound network is limited to
an allowlist that excludes them) — verify against the real APIs once this
runs somewhere with normal internet access.
"""

from __future__ import annotations

import httpx

from app.config import get_settings


def get_client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        timeout=settings.enrichment_http_timeout_seconds,
        headers={"User-Agent": settings.enrichment_user_agent},
    )
