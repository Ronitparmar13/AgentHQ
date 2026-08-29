"""Typed, environment-backed LLM role configuration."""

from dataclasses import dataclass
from os import environ
from typing import Mapping

from app.exceptions import ConfigurationError


@dataclass(frozen=True, slots=True)
class RoleLLMConfig:
    """The provider and model selected for one agent role."""

    provider: str
    model: str

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("LLM provider must not be empty.")
        if not self.model.strip():
            raise ValueError("LLM model must not be empty.")
        object.__setattr__(self, "provider", self.provider.strip())
        object.__setattr__(self, "model", self.model.strip())


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """Manager configuration plus any explicitly configured future roles."""

    manager: RoleLLMConfig
    future_roles: Mapping[str, RoleLLMConfig]

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> "LLMConfig":
        values = environ if environment is None else environment
        manager = RoleLLMConfig(
            provider=cls._required(values, "AGENT_MANAGER_PROVIDER"),
            model=cls._required(values, "AGENT_MANAGER_MODEL"),
        )
        future_roles: dict[str, RoleLLMConfig] = {}
        for role in ("DESIGNER", "FRONTEND", "BACKEND", "QA", "UTILITY"):
            provider = values.get(f"AGENT_{role}_PROVIDER")
            model = values.get(f"AGENT_{role}_MODEL")
            if provider is None and model is None:
                continue
            if provider is None:
                raise ConfigurationError(f"AGENT_{role}_PROVIDER")
            if model is None:
                raise ConfigurationError(f"AGENT_{role}_MODEL")
            future_roles[role] = RoleLLMConfig(provider=provider, model=model)
        return cls(manager=manager, future_roles=future_roles)

    @property
    def role_configs(self) -> dict[str, tuple[str, str]]:
        """Return the router's stable ``ROLE -> (provider, model)`` mapping."""
        return {
            "MANAGER": (self.manager.provider, self.manager.model),
            **{
                role: (config.provider, config.model)
                for role, config in self.future_roles.items()
            },
        }

    @staticmethod
    def _required(values: Mapping[str, str], variable_name: str) -> str:
        value = values.get(variable_name, "").strip()
        if not value:
            raise ConfigurationError(variable_name)
        return value
