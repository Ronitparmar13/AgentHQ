"""Configurable provider for OpenAI Chat Completions-compatible endpoints."""

from app.exceptions import LLMProviderError
from app.llm.base import BaseLLMProvider
from app.llm.providers._helpers import post_json, response_json


class OpenAICompatibleProvider(BaseLLMProvider):
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        provider_name: str = "openai_compatible",
    ) -> None:
        if not base_url.strip():
            raise ValueError("OpenAI-compatible base_url must not be empty.")
        if not provider_name.strip():
            raise ValueError("OpenAI-compatible provider_name must not be empty.")
        self._base_url = base_url.strip()
        self._api_key = api_key.strip()
        self._provider_name = provider_name.strip()

    def complete(self, prompt: str, model: str, **kwargs: object) -> str:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        response = post_json(
            provider=self._provider_name,
            url=self._base_url,
            headers=headers,
            body={"model": model, "messages": [{"role": "user", "content": prompt}]},
        )
        try:
            content = response_json(self._provider_name, response)["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError(
                self._provider_name,
                "invalid_response",
                f"{self._provider_name} returned an invalid response",
            ) from exc
        return content or ""
