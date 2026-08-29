from app.constants import AgentRole
from app.agents.base import BaseAgent
from app.schemas import AgentResult, ModelConfig


class DesignerAgent(BaseAgent):
    name = "Designer"
    role = AgentRole.designer

    def __init__(self) -> None:
        self.model_config = ModelConfig(provider="stub", model="stub")

    def run(self, task: object, context: dict) -> AgentResult:
        return AgentResult(status="not_implemented", output={}, error="Agent designer is not yet implemented")
