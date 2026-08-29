"""Provider-neutral agent interface."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from app.constants import AgentRole
from app.schemas import AgentResult, ModelConfig

if TYPE_CHECKING:
    from app.models import Task


class BaseAgent(ABC):
    name: str
    role: AgentRole
    model_config: ModelConfig

    @abstractmethod
    def run(self, task: "Task", context: dict) -> AgentResult:
        """Perform one task-level execution and return validated safe output."""
        raise NotImplementedError
