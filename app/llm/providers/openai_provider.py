"""OpenAI Chat Completions HTTP provider."""

from os import environ

from app.exceptions import LLMProviderError
from app.llm.base import BaseLLMProvider
from app.llm.providers._helpers import post_json, response_json


class OpenAIProvider(BaseLLMProvider):
    API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, api_key: str | None = None) -> None:
        raw_key = environ.get("OPENAI_API_KEY", "") if api_key is None else api_key
        self._api_key = raw_key.strip()

    def complete(self, prompt: str, model: str, **kwargs: object) -> str:
        if not self._api_key:
            raise LLMProviderError("openai", "missing_api_key", "OPENAI_API_KEY is not set")
        response = post_json(
            provider="openai",
            url=self.API_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            body={"model": model, "messages": [{"role": "user", "content": prompt}]},
        )
        try:
            content = response_json("openai", response)["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("openai", "invalid_response", "OpenAI returned an invalid response") from exc
        return content or ""
