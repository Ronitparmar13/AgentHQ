"""Agent registry with one real planning agent and future-role stubs."""

from typing import TYPE_CHECKING

from app.agents.backend import BackendAgent
from app.agents.designer import DesignerAgent
from app.agents.frontend import FrontendAgent
from app.agents.manager import ManagerAgent
from app.agents.qa import QAAgent
from app.agents.utility import UtilityAgent
from app.constants import AgentRole

if TYPE_CHECKING:
    from app.llm.router import LLMRouter
    from app.schemas import ModelConfig

AGENT_REGISTRY: dict[AgentRole, object] = {}


def build_registry(llm_router: "LLMRouter", config: object) -> dict[AgentRole, object]:
    """Build agents from a manager ModelConfig or the later AppConfig facade."""
    manager_model_config = getattr(config, "manager_model_config", config)
    AGENT_REGISTRY.clear()
    AGENT_REGISTRY.update(
        {
            AgentRole.manager: ManagerAgent(llm_router, manager_model_config),
            AgentRole.designer: DesignerAgent(),
            AgentRole.frontend: FrontendAgent(),
            AgentRole.backend: BackendAgent(),
            AgentRole.qa: QAAgent(),
            AgentRole.utility: UtilityAgent(),
        }
    )
    return AGENT_REGISTRY


__all__ = ["AGENT_REGISTRY", "ManagerAgent", "build_registry"]
