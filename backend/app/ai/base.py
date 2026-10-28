"""Shared types for the app/ai/ package — AI-powered recommendations
("För dig"/swipe discovery) and AI-generated collections. One suggestion
shape works for both use cases: recommendations.py fills media_type_guess
(for the Request it becomes if swiped right), collections.py leaves it
unset (a collection only ever holds books already in the library, so
there's no Request to guess a media type for).
"""

from __future__ import annotations

from dataclasses import dataclass


class AIProviderError(Exception):
    """Any failure talking to or parsing a response from an AI provider —
    caught at the route layer and turned into a clean 502, never a 500.
    """


@dataclass
class AISuggestion:
    title: str
    author: str | None
    reason: str | None
    # "series" | "ebook" | "manga" | None — a raw string here rather than
    # RequestMediaType so app/ai/ doesn't need to import the models layer
    # just to validate an LLM's free-text guess; callers that need it as
    # a Request.media_type validate/coerce it themselves.
    media_type_guess: str | None = None
