from collections.abc import Callable
from unittest.mock import MagicMock, patch

import httpx
import pytest
from hypothesis import given, settings, strategies as st

from app.exceptions import ConfigurationError, LLMProviderError
from app.llm import BaseLLMProvider, LLMConfig, LLMRouter
from app.llm.providers import build_provider_registry
from app.llm.providers.anthropic_provider import AnthropicProvider
from app.llm.providers.gemini_provider import GeminiProvider
from app.llm.providers.openai_compatible_provider import OpenAICompatibleProvider
from app.llm.providers.openai_provider import OpenAIProvider


class EchoProvider(BaseLLMProvider):
    def complete(self, prompt: str, model: str, **kwargs: object) -> str:
        return f"{model}:{prompt}"


def response(status_code: int, payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


def test_base_provider_is_an_abstract_contract() -> None:
    with pytest.raises(TypeError):
        BaseLLMProvider()
    assert EchoProvider().complete("hello", "test-model") == "test-model:hello"


def test_router_selects_provider_without_provider_specific_logic() -> None:
    provider = MagicMock(spec=BaseLLMProvider)
    provider.complete.return_value = "result"
    router = LLMRouter({"MANAGER": ("fake", "configured-model")}, {"fake": provider})

    assert router.complete("MANAGER", "safe prompt", temperature=0) == "result"
    provider.complete.assert_called_once_with(
        prompt="safe prompt", model="configured-model", temperature=0
    )


@pytest.mark.parametrize("role", ["manager", "MANAGER-1", "", "A" * 65])
def test_router_rejects_malformed_role_identifiers(role: str) -> None:
    provider = MagicMock(spec=BaseLLMProvider)
    router = LLMRouter({"MANAGER": ("fake", "model")}, {"fake": provider})

    with pytest.raises(ValueError, match="Invalid role identifier"):
        router.complete(role, "prompt")
    provider.complete.assert_not_called()


def test_router_rejects_unconfigured_role_and_missing_provider() -> None:
    router = LLMRouter({"MANAGER": ("missing", "model")}, {})
    with pytest.raises(ConfigurationError) as missing_provider:
        router.complete("MANAGER", "prompt")
    assert missing_provider.value.variable_name == "AGENT_MANAGER_PROVIDER"

    with pytest.raises(ConfigurationError) as missing_role:
        router.complete("DESIGNER", "prompt")
    assert missing_role.value.variable_name == "AGENT_DESIGNER_MODEL"


# Feature: agenthq-mvp-phase1, Property 16: LLM router rejects all out-of-bounds prompts.
@given(
    st.one_of(
        st.just(""),
        st.integers(min_value=32_769, max_value=32_780).map(lambda length: "x" * length),
    )
)
@settings(max_examples=20)
def test_router_rejects_out_of_bounds_prompts_without_delegating(prompt: str) -> None:
    provider = MagicMock(spec=BaseLLMProvider)
    router = LLMRouter({"MANAGER": ("fake", "model")}, {"fake": provider})

    with pytest.raises(ValueError, match="Prompt length"):
        router.complete("MANAGER", prompt)
    provider.complete.assert_not_called()


def test_llm_config_requires_manager_and_exposes_optional_roles() -> None:
    config = LLMConfig.from_environment(
        {
            "AGENT_MANAGER_PROVIDER": "anthropic",
            "AGENT_MANAGER_MODEL": "model-a",
            "AGENT_QA_PROVIDER": "openai",
            "AGENT_QA_MODEL": "model-b",
        }
    )
    assert config.role_configs == {
        "MANAGER": ("anthropic", "model-a"),
        "QA": ("openai", "model-b"),
    }
    with pytest.raises(ConfigurationError) as exc_info:
        LLMConfig.from_environment({"AGENT_MANAGER_MODEL": "model"})
    assert exc_info.value.variable_name == "AGENT_MANAGER_PROVIDER"
    with pytest.raises(ConfigurationError) as incomplete_role:
        LLMConfig.from_environment(
            {
                "AGENT_MANAGER_PROVIDER": "openai",
                "AGENT_MANAGER_MODEL": "model",
                "AGENT_QA_PROVIDER": "openai",
            }
        )
    assert incomplete_role.value.variable_name == "AGENT_QA_MODEL"


@pytest.mark.parametrize(
    ("provider", "provider_name"),
    [
        (OpenAIProvider(api_key=""), "openai"),
        (AnthropicProvider(api_key=""), "anthropic"),
        (GeminiProvider(api_key=""), "gemini"),
    ],
)
def test_named_providers_fail_safely_when_credentials_are_missing(
    provider: BaseLLMProvider, provider_name: str
) -> None:
    with patch("app.llm.providers._helpers.httpx.post") as post:
        with pytest.raises(LLMProviderError) as exc_info:
            provider.complete("prompt", "model")
    assert exc_info.value.provider == provider_name
    assert exc_info.value.category == "missing_api_key"
    post.assert_not_called()


@pytest.mark.parametrize(
    ("factory", "provider_name"),
    [
        (lambda: OpenAIProvider(api_key="key"), "openai"),
        (lambda: AnthropicProvider(api_key="key"), "anthropic"),
        (lambda: GeminiProvider(api_key="key"), "gemini"),
        (
            lambda: OpenAICompatibleProvider(
                "https://compatible.example/v1/chat/completions", "key", "compatible"
            ),
            "compatible",
        ),
    ],
)
@pytest.mark.parametrize(
    ("status_code", "category"),
    [(401, "auth_failure"), (429, "rate_limit"), (500, "api_error")],
)
def test_providers_normalize_http_failures(
    factory: Callable[[], BaseLLMProvider], provider_name: str, status_code: int, category: str
) -> None:
    with patch(
        "app.llm.providers._helpers.httpx.post", return_value=response(status_code, {})
    ):
        with pytest.raises(LLMProviderError) as exc_info:
            factory().complete("prompt", "model")
    assert exc_info.value.provider == provider_name
    assert exc_info.value.category == category


@pytest.mark.parametrize(
    ("provider", "payload", "expected"),
    [
        (
            OpenAIProvider(api_key="openai-key"),
            {"choices": [{"message": {"content": "openai result"}}]},
            "openai result",
        ),
        (
            AnthropicProvider(api_key="anthropic-key"),
            {"content": [{"text": "anthropic result"}]},
            "anthropic result",
        ),
        (
            GeminiProvider(api_key="gemini-key"),
            {"candidates": [{"content": {"parts": [{"text": "gemini result"}]}}]},
            "gemini result",
        ),
        (
            OpenAICompatibleProvider(
                "https://compatible.example/v1/chat/completions", "compatible-key", "compatible"
            ),
            {"choices": [{"message": {"content": "compatible result"}}]},
            "compatible result",
        ),
    ],
)
def test_providers_parse_successful_responses(
    provider: BaseLLMProvider, payload: dict[str, object], expected: str
) -> None:
    with patch(
        "app.llm.providers._helpers.httpx.post", return_value=response(200, payload)
    ) as post:
        assert provider.complete("short prompt", "configured-model") == expected
    assert post.call_count == 1


def test_openai_compatible_provider_is_configurable_and_allows_no_auth() -> None:
    provider = OpenAICompatibleProvider(
        base_url="http://localhost:9999/v1/chat/completions",
        api_key="",
        provider_name="local",
    )
    with patch(
        "app.llm.providers._helpers.httpx.post",
        return_value=response(200, {"choices": [{"message": {"content": "local"}}]}),
    ) as post:
        assert provider.complete("prompt", "local-model") == "local"

    assert post.call_args.args[0] == "http://localhost:9999/v1/chat/completions"
    assert post.call_args.kwargs["json"]["model"] == "local-model"
    assert "Authorization" not in post.call_args.kwargs["headers"]


def test_provider_registry_registers_builtins_and_opt_in_compatible_endpoints() -> None:
    registry = build_provider_registry(
        {
            "OPENAI_API_KEY": "openai-key",
            "OAICOMPAT_LOCAL_BASE_URL": "http://localhost:9999/v1/chat/completions",
            "OAICOMPAT_LOCAL_API_KEY": "local-key",
        }
    )
    assert set(registry) == {"openai", "anthropic", "gemini", "local"}
    assert isinstance(registry["local"], OpenAICompatibleProvider)
