"""Tests for the three app/ai/*_client.py provider modules — each
`generate()` takes an injectable `client` (same convention as
app/enrichment/*.py's providers), so a minimal fake httpx.Client stands in
for a real network call. Only the request-building/response-extraction
logic is under test here; app/ai/parsing.py's own JSON parsing is tested
separately in test_ai_parsing.py (generate() now returns raw text, not
parsed suggestions — see dispatch.py's docstring for why).
"""

from __future__ import annotations

import httpx
import pytest

from app.ai import claude_client, gemini_client, openai_client
from app.ai.base import AIProviderError


class _FakeResponse:
    def __init__(self, json_data: dict, status_code: int = 200) -> None:
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)  # type: ignore[arg-type]

    def json(self) -> dict:
        return self._json_data


class _FakeClient:
    def __init__(self, response: _FakeResponse | None = None, *, raise_error: Exception | None = None) -> None:
        self.response = response
        self.raise_error = raise_error
        self.calls: list[tuple[str, dict, dict]] = []

    def post(self, url, *, headers=None, json=None):
        self.calls.append((url, headers or {}, json or {}))
        if self.raise_error is not None:
            raise self.raise_error
        return self.response

    def close(self) -> None:
        pass


def test_openai_generate_returns_message_content_and_sends_bearer_token():
    fake = _FakeClient(_FakeResponse({"choices": [{"message": {"content": '{"recommendations": []}'}}]}))

    text = openai_client.generate(system_prompt="sys", user_prompt="usr", api_key="sk-test", model="", client=fake)

    assert text == '{"recommendations": []}'
    url, headers, body = fake.calls[0]
    assert url == openai_client.API_URL
    assert headers["Authorization"] == "Bearer sk-test"
    assert body["model"] == openai_client.DEFAULT_MODEL
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0] == {"role": "system", "content": "sys"}


def test_openai_generate_uses_explicit_model_when_given():
    fake = _FakeClient(_FakeResponse({"choices": [{"message": {"content": "{}"}}]}))
    openai_client.generate(system_prompt="s", user_prompt="u", api_key="k", model="gpt-4o", client=fake)
    assert fake.calls[0][2]["model"] == "gpt-4o"


def test_openai_generate_raises_ai_provider_error_on_http_failure():
    fake = _FakeClient(raise_error=httpx.ConnectError("down", request=None))
    with pytest.raises(AIProviderError):
        openai_client.generate(system_prompt="s", user_prompt="u", api_key="k", model="", client=fake)


def test_openai_generate_raises_on_unexpected_response_shape():
    fake = _FakeClient(_FakeResponse({"unexpected": True}))
    with pytest.raises(AIProviderError):
        openai_client.generate(system_prompt="s", user_prompt="u", api_key="k", model="", client=fake)


def test_claude_generate_returns_text_and_sends_api_key_header():
    fake = _FakeClient(_FakeResponse({"content": [{"text": '{"recommendations": []}'}]}))

    text = claude_client.generate(system_prompt="sys", user_prompt="usr", api_key="claude-key", model="", client=fake)

    assert text == '{"recommendations": []}'
    url, headers, body = fake.calls[0]
    assert url == claude_client.API_URL
    assert headers["x-api-key"] == "claude-key"
    assert headers["anthropic-version"] == claude_client.ANTHROPIC_VERSION
    assert body["system"] == "sys"
    assert body["messages"] == [{"role": "user", "content": "usr"}]


def test_claude_generate_raises_ai_provider_error_on_http_failure():
    fake = _FakeClient(raise_error=httpx.ConnectError("down", request=None))
    with pytest.raises(AIProviderError):
        claude_client.generate(system_prompt="s", user_prompt="u", api_key="k", model="", client=fake)


def test_gemini_generate_returns_text_and_sends_api_key_header():
    fake = _FakeClient(_FakeResponse({"candidates": [{"content": {"parts": [{"text": '{"recommendations": []}'}]}}]}))

    text = gemini_client.generate(system_prompt="sys", user_prompt="usr", api_key="gemini-key", model="", client=fake)

    assert text == '{"recommendations": []}'
    url, headers, body = fake.calls[0]
    assert gemini_client.DEFAULT_MODEL in url
    assert headers["x-goog-api-key"] == "gemini-key"
    assert body["generationConfig"] == {"responseMimeType": "application/json"}


def test_gemini_generate_uses_explicit_model_in_url():
    fake = _FakeClient(_FakeResponse({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}))
    gemini_client.generate(system_prompt="s", user_prompt="u", api_key="k", model="gemini-2.5-pro", client=fake)
    assert "gemini-2.5-pro" in fake.calls[0][0]


def test_gemini_generate_raises_ai_provider_error_on_http_failure():
    fake = _FakeClient(raise_error=httpx.ConnectError("down", request=None))
    with pytest.raises(AIProviderError):
        gemini_client.generate(system_prompt="s", user_prompt="u", api_key="k", model="", client=fake)
