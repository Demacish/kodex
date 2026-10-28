"""Claude provider — Messages API. No native enforced-JSON response mode
used here (see app/ai/parsing.py's docstring for why that's fine), so the
system prompt's own "respond with ONLY the JSON object, no other text" is
what keeps the response parseable — app/ai/parsing.py's fence-stripping is
the safety net for when a response still wraps it in ```json anyway.
"""

from __future__ import annotations

import httpx

from app.ai.base import AIProviderError
from app.ai.http import get_client

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-5"
ANTHROPIC_VERSION = "2023-06-01"


def generate(
    *, system_prompt: str, user_prompt: str, api_key: str, model: str, client: httpx.Client | None = None
) -> str:
    owned_client = client or get_client()
    try:
        response = owned_client.post(
            API_URL,
            headers={"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION},
            json={
                "model": model or DEFAULT_MODEL,
                "max_tokens": 4096,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise AIProviderError(f"Claude request failed: {exc}") from exc
    finally:
        if client is None:
            owned_client.close()

    try:
        text = data["content"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIProviderError(f"Unexpected Claude response shape: {exc}") from exc

    return text
