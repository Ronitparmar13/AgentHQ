"""Internal error handling shared only by concrete HTTP providers."""

from typing import Any

import httpx

from app.exceptions import LLMProviderError


def post_json(
    *,
    provider: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: dict[str, Any],
) -> httpx.Response:
    """Make a provider request and normalize transport and status failures."""
    try:
        response = httpx.post(url, headers=headers, json=body, timeout=60)
    except httpx.RequestError as exc:
        raise LLMProviderError(
            provider, "network_error", f"Network error calling {provider}"
        ) from exc
    if response.status_code in (401, 403):
        raise LLMProviderError(
            provider, "auth_failure", f"{provider} authentication failed"
        )
    if response.status_code == 429:
        raise LLMProviderError(provider, "rate_limit", f"{provider} rate limit exceeded")
    if not response.is_success:
        raise LLMProviderError(
            provider, "api_error", f"{provider} returned HTTP {response.status_code}"
        )
    return response


def response_json(provider: str, response: httpx.Response) -> dict[str, Any]:
    """Return an object response while keeping malformed payloads provider-safe."""
    try:
        payload = response.json()
    except (ValueError, TypeError) as exc:
        raise LLMProviderError(provider, "invalid_response", f"{provider} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise LLMProviderError(provider, "invalid_response", f"{provider} returned an invalid response")
    return payload
