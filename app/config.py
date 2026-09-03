"""Environment-backed application configuration."""

import os

from app.constants import AgentRole
from app.exceptions import ConfigurationError
from app.schemas import ModelConfig

REQUIRED_VARS = [
    "SECRET_KEY",
    "AGENT_MANAGER_MODEL",
    "AGENT_MANAGER_PROVIDER",
]

STUB_ROLES = [
    AgentRole.designer,
    AgentRole.frontend,
    AgentRole.backend,
    AgentRole.qa,
    AgentRole.utility,
]


class AppConfig:
    def __init__(self, overrides: dict | None = None) -> None:
        self._env: dict[str, str] = {**os.environ, **(overrides or {})}

        for var in REQUIRED_VARS:
            if not self._env.get(var):
                raise ConfigurationError(variable_name=var)

        self.secret_key = self._env["SECRET_KEY"]
        self.database_url = self._env.get("DATABASE_URL", "sqlite:///agenthq.db")
        self._load_model_configs()

    def _load_model_configs(self) -> None:
        self.llm_role_configs: dict[str, tuple[str, str]] = {}

        manager_model = self._env["AGENT_MANAGER_MODEL"]
        manager_provider = self._env["AGENT_MANAGER_PROVIDER"]
        self.llm_role_configs["MANAGER"] = (manager_provider, manager_model)
        self.manager_model_config = ModelConfig(provider=manager_provider, model=manager_model)

        for role in STUB_ROLES:
            role_upper = role.value.upper()
            model = self._env.get(f"AGENT_{role_upper}_MODEL", "stub")
            provider = self._env.get(f"AGENT_{role_upper}_PROVIDER", "stub")
            self.llm_role_configs[role_upper] = (provider, model)
