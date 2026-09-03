"""Built-in and opt-in LLM provider registration."""

from os import environ
from typing import Mapping

from app.llm.base import BaseLLMProvider
from app.llm.providers.anthropic_provider import AnthropicProvider
from app.llm.providers.gemini_provider import GeminiProvider
from app.llm.providers.openai_compatible_provider import OpenAICompatibleProvider
from app.llm.providers.openai_provider import OpenAIProvider

_COMPAT_PREFIX = "OAICOMPAT_"
_COMPAT_SUFFIX = "_BASE_URL"


def build_provider_registry(
    environment: Mapping[str, str] | None = None,
) -> dict[str, BaseLLMProvider]:
    """Build built-in providers and explicitly configured compatible providers.

    Named providers are always registered. Compatible providers are opt-in through
    ``OAICOMPAT_<NAME>_BASE_URL`` and may supply ``..._API_KEY`` separately.
    """
    values = environ if environment is None else environment
    registry: dict[str, BaseLLMProvider] = {
        "openai": OpenAIProvider(api_key=values.get("OPENAI_API_KEY", "")),
        "anthropic": AnthropicProvider(api_key=values.get("ANTHROPIC_API_KEY", "")),
        "gemini": GeminiProvider(api_key=values.get("GEMINI_API_KEY", "")),
        "openrouter": OpenAICompatibleProvider(
            base_url="https://openrouter.ai/api/v1/chat/completions",
            api_key=values.get("OPENROUTER_API_KEY", ""),
            provider_name="openrouter",
        ),
    }
    for key, base_url in values.items():
        if not (key.startswith(_COMPAT_PREFIX) and key.endswith(_COMPAT_SUFFIX) and base_url):
            continue
        name = key[len(_COMPAT_PREFIX) : -len(_COMPAT_SUFFIX)].lower()
        if not name:
            continue
        if name in registry:
            continue
        registry[name] = OpenAICompatibleProvider(
            base_url=base_url,
            api_key=values.get(f"{_COMPAT_PREFIX}{name.upper()}_API_KEY", ""),
            provider_name=name,
        )
    return registry


__all__ = [
    "AnthropicProvider",
    "GeminiProvider",
    "OpenAICompatibleProvider",
    "OpenAIProvider",
    "build_provider_registry",
]
