"""Google Gemini generateContent HTTP provider."""

from os import environ
from urllib.parse import quote

from app.exceptions import LLMProviderError
from app.llm.base import BaseLLMProvider
from app.llm.providers._helpers import post_json, response_json


class GeminiProvider(BaseLLMProvider):
    API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str | None = None) -> None:
        raw_key = environ.get("GEMINI_API_KEY", "") if api_key is None else api_key
        self._api_key = raw_key.strip()

    def complete(self, prompt: str, model: str, **kwargs: object) -> str:
        if not self._api_key:
            raise LLMProviderError("gemini", "missing_api_key", "GEMINI_API_KEY is not set")
        response = post_json(
            provider="gemini",
            url=(
                f"{self.API_BASE}/{quote(model, safe='')}:generateContent"
                f"?key={quote(self._api_key, safe='')}"
            ),
            headers={"Content-Type": "application/json"},
            body={"contents": [{"parts": [{"text": prompt}]}]},
        )
        try:
            content = response_json("gemini", response)["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError(
                "gemini", "empty_response", "Gemini returned no candidates"
            ) from exc
        return content or ""
