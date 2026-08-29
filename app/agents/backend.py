from app.constants import AgentRole
from app.agents.base import BaseAgent
from app.schemas import AgentResult, ModelConfig


class BackendAgent(BaseAgent):
    name = "Backend"
    role = AgentRole.backend

    def __init__(self) -> None:
        self.model_config = ModelConfig(provider="stub", model="stub")

    def run(self, task: object, context: dict) -> AgentResult:
        return AgentResult(status="not_implemented", output={}, error="Agent backend is not yet implemented")
