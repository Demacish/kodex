"""Shared httpx client factory for the app/ai/ provider modules — same
"pass a client in for tests" convention as app/enrichment/http.py, but its
own (longer) timeout: an LLM completion for 15-20 structured
recommendations routinely takes far longer than a metadata-provider
lookup.
"""

from __future__ import annotations

import httpx

_AI_HTTP_TIMEOUT_SECONDS = 60.0


def get_client() -> httpx.Client:
    return httpx.Client(timeout=_AI_HTTP_TIMEOUT_SECONDS)
