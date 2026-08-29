from app.constants import AgentRole
from app.agents.base import BaseAgent
from app.schemas import AgentResult, ModelConfig


class UtilityAgent(BaseAgent):
    name = "Utility"
    role = AgentRole.utility

    def __init__(self) -> None:
        self.model_config = ModelConfig(provider="stub", model="stub")

    def run(self, task: object, context: dict) -> AgentResult:
        return AgentResult(status="not_implemented", output={}, error="Agent utility is not yet implemented")
