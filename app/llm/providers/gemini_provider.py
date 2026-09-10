"""Google Gemini generateContent HTTP provider."""

from os import environ
from urllib.parse import quote

import httpx

from app.exceptions import LLMProviderError
from app.llm.base import BaseLLMProvider
from app.llm.providers._helpers import response_json


class GeminiProvider(BaseLLMProvider):
    API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str | None = None) -> None:
        raw_key = environ.get("GEMINI_API_KEY", "") if api_key is None else api_key
        self._api_key = raw_key.strip()

    def complete(self, prompt: str, model: str, **kwargs: object) -> str:
        if not self._api_key:
            raise LLMProviderError("gemini", "missing_api_key", "GEMINI_API_KEY is not set")
        url = f"{self.API_BASE}/{quote(model, safe='')}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,
        }
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            response = httpx.post(url, headers=headers, json=body, timeout=60)
        except httpx.RequestError as exc:
            raise LLMProviderError("gemini", "network_error", f"Network error calling gemini") from exc
        self._raise_for_gemini_error(response)
        try:
            content = response_json("gemini", response)["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError(
                "gemini", "empty_response", "Gemini returned no candidates"
            ) from exc
        return content or ""

    def _raise_for_gemini_error(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        error_msg = f"gemini returned HTTP {response.status_code}"
        error_category = "api_error"
        try:
            payload = response.json()
            error = payload.get("error", {})
            if isinstance(error, dict):
                msg = error.get("message")
                status = error.get("status")
                reason = None
                for detail in error.get("details", []):
                    if detail.get("@type") == "type.googleapis.com/google.rpc.ErrorInfo":
                        reason = detail.get("reason")
                        break
                if msg:
                    error_msg = msg
                if status == "UNAUTHENTICATED" or reason in ("API_KEY_INVALID", "API_KEY_EXPIRED"):
                    error_category = "auth_failure"
                elif status == "RESOURCE_EXHAUSTED" or reason == "RATE_LIMIT_EXCEEDED":
                    error_category = "rate_limit"
        except (ValueError, TypeError):
            pass
        if error_category == "api_error":
            if response.status_code in (401, 403):
                error_category = "auth_failure"
            elif response.status_code == 429:
                error_category = "rate_limit"
        raise LLMProviderError("gemini", error_category, error_msg)
