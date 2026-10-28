"""Gemini provider — generateContent REST API with
`generationConfig.responseMimeType: "application/json"`, Gemini's own
enforced-JSON mode (no full response schema, same trade-off as
openai_client.py's plain `json_object` mode).
"""

from __future__ import annotations

import httpx

from app.ai.base import AIProviderError
from app.ai.http import get_client

DEFAULT_MODEL = "gemini-2.5-flash"


def generate(
    *, system_prompt: str, user_prompt: str, api_key: str, model: str, client: httpx.Client | None = None
) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model or DEFAULT_MODEL}:generateContent"
    owned_client = client or get_client()
    try:
        response = owned_client.post(
            url,
            headers={"x-goog-api-key": api_key},
            json={
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            },
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise AIProviderError(f"Gemini request failed: {exc}") from exc
    finally:
        if client is None:
            owned_client.close()

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIProviderError(f"Unexpected Gemini response shape: {exc}") from exc

    return text
