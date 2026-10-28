"""Routes to the right provider client module by AIProvider — same
"dispatch by an enum" shape as app/enrichment/engine.py's
provider_for_book, just for the AI providers instead of metadata ones.
Returns the provider's raw response text; callers (recommendations.py,
collections.py) parse it with whichever app/ai/parsing.py function
matches the response shape they asked for in their own system prompt.
"""

from __future__ import annotations

from app.ai import claude_client, gemini_client, openai_client
from app.ai.base import AIProviderError
from app.models.enums import AIProvider

_GENERATORS = {
    AIProvider.OPENAI: openai_client.generate,
    AIProvider.CLAUDE: claude_client.generate,
    AIProvider.GEMINI: gemini_client.generate,
}


def generate_text(provider: AIProvider, *, system_prompt: str, user_prompt: str, api_key: str, model: str) -> str:
    generator = _GENERATORS.get(provider)
    if generator is None:
        raise AIProviderError(f"Unknown AI provider: {provider}")
    return generator(system_prompt=system_prompt, user_prompt=user_prompt, api_key=api_key, model=model)
