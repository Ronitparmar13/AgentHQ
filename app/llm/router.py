"""Provider-agnostic role-to-provider completion routing."""

import re
from collections.abc import Mapping

from app.exceptions import ConfigurationError
from app.llm.base import BaseLLMProvider
from app.llm.config import RoleLLMConfig

_ROLE_PATTERN = re.compile(r"^[A-Z_]{1,64}$")
_MAX_PROMPT_LENGTH = 32_768


class LLMRouter:
    """Resolve an agent role to its configured provider and model."""

    def __init__(
        self,
        role_configs: Mapping[str, tuple[str, str] | RoleLLMConfig],
        provider_registry: Mapping[str, BaseLLMProvider],
    ) -> None:
        self._role_configs = {
            role: self._as_pair(config) for role, config in role_configs.items()
        }
        self._provider_registry = dict(provider_registry)

    def complete(self, role: str, prompt: str, **kwargs: object) -> str:
        if not isinstance(role, str) or _ROLE_PATTERN.fullmatch(role) is None:
            raise ValueError(f"Invalid role identifier: {role!r}")
        if role not in self._role_configs:
            raise ConfigurationError(variable_name=f"AGENT_{role}_MODEL")
        if not isinstance(prompt, str) or not prompt or len(prompt) > _MAX_PROMPT_LENGTH:
            length = len(prompt) if isinstance(prompt, str) else 0
            raise ValueError(
                f"Prompt length {length} is not in range [1, {_MAX_PROMPT_LENGTH}]"
            )

        provider_name, model = self._role_configs[role]
        provider = self._provider_registry.get(provider_name)
        if provider is None:
            raise ConfigurationError(variable_name=f"AGENT_{role}_PROVIDER")
        return provider.complete(prompt=prompt, model=model, **kwargs)

    @staticmethod
    def _as_pair(config: tuple[str, str] | RoleLLMConfig) -> tuple[str, str]:
        if isinstance(config, RoleLLMConfig):
            return config.provider, config.model
        provider, model = config
        if not provider or not model:
            raise ValueError("Role provider and model must not be empty.")
        return provider, model
