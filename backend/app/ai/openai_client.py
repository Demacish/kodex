"""OpenAI provider — Chat Completions API with `response_format:
{"type": "json_object"}`, which guarantees syntactically valid JSON (not a
full schema like ReadMeABook's BookDate uses, but simpler and enough given
app/ai/parsing.py already tolerates/drops malformed individual entries).
"""

from __future__ import annotations

import httpx

from app.ai.base import AIProviderError
from app.ai.http import get_client

API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o-mini"


def generate(
    *, system_prompt: str, user_prompt: str, api_key: str, model: str, client: httpx.Client | None = None
) -> str:
    owned_client = client or get_client()
    try:
        response = owned_client.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model or DEFAULT_MODEL,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise AIProviderError(f"OpenAI request failed: {exc}") from exc
    finally:
        if client is None:
            owned_client.close()

    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIProviderError(f"Unexpected OpenAI response shape: {exc}") from exc

    return text
