"""Turns a raw LLM text response into structured data — shared by every
caller of app/ai/dispatch.py's generate_text, since only Claude (of the
three providers) lacks a native structured-output mode Kodex actually
enforces (see openai_client.py/gemini_client.py's response_format/
responseMimeType vs claude_client.py's plain-prompt instruction) — even
the two providers with "enforced" JSON still route through this, both for
the ```json fence-stripping any provider's raw text can come back wrapped
in regardless of the requested mode, and so there's one place responsible
for turning a malformed individual entry into "dropped", not fatal to the
whole batch.
"""

from __future__ import annotations

import json
import re

from app.ai.base import AIProviderError, AISuggestion

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    if match := _FENCE_RE.search(text):
        return match.group(1)
    return text.strip()


def _parse_json_object(raw_text: str) -> dict:
    cleaned = _strip_code_fence(raw_text)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AIProviderError(f"AI response was not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise AIProviderError("AI response JSON was not an object")
    return payload


def _parse_suggestion_list(items: object) -> list[AISuggestion]:
    if not isinstance(items, list):
        return []
    suggestions = []
    for item in items:
        if not isinstance(item, dict) or not item.get("title"):
            continue  # a malformed single entry is dropped, not fatal to the whole batch
        suggestions.append(
            AISuggestion(
                title=str(item["title"]).strip(),
                author=(str(item["author"]).strip() if item.get("author") else None),
                reason=(str(item["reason"]).strip() if item.get("reason") else None),
                media_type_guess=(str(item["media_type"]).strip().lower() if item.get("media_type") else None),
            )
        )
    return suggestions


def parse_recommendations(raw_text: str) -> list[AISuggestion]:
    """Expects `{"recommendations": [{"title", "author", "reason",
    "media_type"}, ...]}` — see recommendations.py's _SYSTEM_PROMPT.
    """
    payload = _parse_json_object(raw_text)
    items = payload.get("recommendations")
    if not isinstance(items, list):
        raise AIProviderError("AI response JSON had no 'recommendations' list")
    return _parse_suggestion_list(items)


def parse_collection_selection(raw_text: str) -> tuple[str | None, list[AISuggestion]]:
    """Expects `{"collection_name": str, "books": [{"title", "author",
    "reason"}, ...]}` — see collections.py's _SYSTEM_PROMPT. `media_type`
    is never part of this shape (a collection only ever holds books
    already in the library), so the resulting AISuggestion.media_type_guess
    is always None.
    """
    payload = _parse_json_object(raw_text)
    items = payload.get("books")
    if not isinstance(items, list):
        raise AIProviderError("AI response JSON had no 'books' list")
    name = payload.get("collection_name")
    return (str(name).strip() if name else None), _parse_suggestion_list(items)
