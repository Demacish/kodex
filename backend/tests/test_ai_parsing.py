"""Tests for app/ai/parsing.py — turning raw LLM text into AISuggestion
lists (recommendations) or a (name, suggestions) pair (collections).
"""

from __future__ import annotations

import pytest

from app.ai.base import AIProviderError
from app.ai.parsing import parse_collection_selection, parse_recommendations


def test_parse_recommendations_happy_path():
    raw = '{"recommendations": [{"title": "Bramble", "author": "Kentaro Miura", "reason": "dark fantasy", "media_type": "manga"}]}'
    result = parse_recommendations(raw)
    assert len(result) == 1
    assert result[0].title == "Bramble"
    assert result[0].author == "Kentaro Miura"
    assert result[0].media_type_guess == "manga"


def test_parse_recommendations_strips_code_fence():
    raw = '```json\n{"recommendations": [{"title": "X"}]}\n```'
    result = parse_recommendations(raw)
    assert result[0].title == "X"


def test_parse_recommendations_drops_malformed_entries_without_failing():
    raw = '{"recommendations": [{"author": "no title here"}, {"title": "Valid"}]}'
    result = parse_recommendations(raw)
    assert [s.title for s in result] == ["Valid"]


def test_parse_recommendations_raises_on_invalid_json():
    with pytest.raises(AIProviderError):
        parse_recommendations("not json at all")


def test_parse_recommendations_raises_when_key_missing():
    with pytest.raises(AIProviderError):
        parse_recommendations('{"something_else": []}')


def test_parse_recommendations_optional_fields_default_to_none():
    result = parse_recommendations('{"recommendations": [{"title": "Only Title"}]}')
    assert result[0].author is None
    assert result[0].reason is None
    assert result[0].media_type_guess is None


def test_parse_collection_selection_happy_path():
    raw = (
        '{"collection_name": "Rymdoperor", "books": [{"title": "Saga", "author": "Fiona Staples", "reason": "space"}]}'
    )
    name, suggestions = parse_collection_selection(raw)
    assert name == "Rymdoperor"
    assert len(suggestions) == 1
    assert suggestions[0].title == "Saga"
    # Collections never carry a media_type — a collection only ever holds
    # already-owned books, see collections.py's _SYSTEM_PROMPT.
    assert suggestions[0].media_type_guess is None


def test_parse_collection_selection_missing_name_returns_none():
    name, suggestions = parse_collection_selection('{"books": [{"title": "X"}]}')
    assert name is None
    assert len(suggestions) == 1


def test_parse_collection_selection_raises_when_books_key_missing():
    with pytest.raises(AIProviderError):
        parse_collection_selection('{"collection_name": "X"}')
