"""Anthropic Messages API HTTP provider."""

from os import environ

from app.exceptions import LLMProviderError
from app.llm.base import BaseLLMProvider
from app.llm.providers._helpers import post_json, response_json


class AnthropicProvider(BaseLLMProvider):
    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(self, api_key: str | None = None) -> None:
        raw_key = environ.get("ANTHROPIC_API_KEY", "") if api_key is None else api_key
        self._api_key = raw_key.strip()

    def complete(self, prompt: str, model: str, **kwargs: object) -> str:
        if not self._api_key:
            raise LLMProviderError(
                "anthropic", "missing_api_key", "ANTHROPIC_API_KEY is not set"
            )
        response = post_json(
            provider="anthropic",
            url=self.API_URL,
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": self.API_VERSION,
                "Content-Type": "application/json",
            },
            body={
                "model": model,
                "max_tokens": kwargs.get("max_tokens", 4096),
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        try:
            content = response_json("anthropic", response)["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError(
                "anthropic", "invalid_response", "Anthropic returned an invalid response"
            ) from exc
        return content or ""
