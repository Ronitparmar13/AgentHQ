from app.constants import AgentRole
from app.agents.base import BaseAgent
from app.schemas import AgentResult, ModelConfig


class FrontendAgent(BaseAgent):
    name = "Frontend"
    role = AgentRole.frontend

    def __init__(self) -> None:
        self.model_config = ModelConfig(provider="stub", model="stub")

    def run(self, task: object, context: dict) -> AgentResult:
        return AgentResult(status="not_implemented", output={}, error="Agent frontend is not yet implemented")
