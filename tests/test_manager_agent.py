from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.manager import ManagerAgent
from app.agents import AGENT_REGISTRY, build_registry
from app.constants import AgentRole
from app.exceptions import LLMProviderError
from app.llm.base import BaseLLMProvider
from app.llm.router import LLMRouter
from app.models import Event, Project, Task
from app.schemas import ModelConfig
from app.services.event_service import EventService
from app.services.task_service import TaskService


def valid_plan_json() -> str:
    return """{
      "tasks": [
        {"local_id": "DESIGN", "title": "Design", "description": "Create design", "assigned_role": "designer", "priority": "high", "dependencies": []},
        {"local_id": "BUILD", "title": "Build", "description": "Build app", "assigned_role": "backend", "priority": "medium", "dependencies": ["DESIGN"]}
      ]
    }"""


def make_manager(raw_response: str | Exception) -> ManagerAgent:
    router = MagicMock()
    if isinstance(raw_response, Exception):
        router.complete.side_effect = raw_response
    else:
        router.complete.return_value = raw_response
    return ManagerAgent(router, ModelConfig(provider="mock", model="mock-model"))


def make_project(session: Session) -> Project:
    project = Project(title="Project", description="Description")
    session.add(project)
    session.commit()
    return project


def test_manager_persists_validated_tasks_dependencies_and_completed_event(session: Session) -> None:
    project = make_project(session)
    manager = make_manager(valid_plan_json())
    events = EventService()
    count = manager.plan(project.id, project.title, project.description, TaskService(events), events, session)

    assert count == 2
    assert session.query(Task).count() == 2
    assert {
        task.title: task.status for task in session.scalars(select(Task).order_by(Task.title))
    } == {"Design": "ready", "Build": "backlog"}
    assert session.scalar(select(Event).where(Event.event_name == "manager.planning_completed")) is not None


@pytest.mark.parametrize(
    "response",
    ["not json", '{"tasks": [{"local_id": "A", "title": "A", "description": "D", "assigned_role": "not-a-role", "priority": "low", "dependencies": []}]}'],
)
def test_manager_rejects_invalid_output_without_persisting_tasks(session: Session, response: str) -> None:
    project = make_project(session)
    manager = make_manager(response)
    with pytest.raises(ValidationError):
        manager.plan(project.id, project.title, project.description, TaskService(), EventService(), session)
    assert session.query(Task).count() == 0


def test_manager_propagates_provider_failure_without_persisting_tasks(session: Session) -> None:
    project = make_project(session)
    manager = make_manager(LLMProviderError("mock", "network_error", "safe failure"))
    with pytest.raises(LLMProviderError):
        manager.plan(project.id, project.title, project.description, TaskService(), EventService(), session)
    assert session.query(Task).count() == 0


def test_manager_prompt_requires_only_the_approved_json_shape() -> None:
    manager = make_manager(valid_plan_json())
    prompt = manager._build_prompt("Title", "Description")
    assert "Return ONLY the JSON object" in prompt
    assert '"local_id"' in prompt
    assert "manager|designer|frontend|backend|qa|utility" in prompt


def test_registry_includes_manager_and_non_executing_specialist_stubs() -> None:
    router = MagicMock()
    registry = build_registry(router, ModelConfig(provider="mock", model="model"))
    assert set(registry) == set(AgentRole)
    for role in AgentRole:
        assert registry[role] is AGENT_REGISTRY[role]
    assert registry[AgentRole.designer].run(None, {}).status == "not_implemented"
    router.complete.assert_not_called()


class _RecordingProvider(BaseLLMProvider):
    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[dict[str, object]] = []

    def complete(self, prompt: str, model: str, **kwargs: object) -> str:
        self.calls.append({"prompt": prompt, "model": model, "kwargs": kwargs})
        return self._response


def test_manager_uses_llm_router_and_validates_raw_response(
    session: Session,
) -> None:
    project = make_project(session)
    provider = _RecordingProvider(valid_plan_json())
    router = LLMRouter({"MANAGER": ("fake", "configured-model")}, {"fake": provider})
    manager = ManagerAgent(router, ModelConfig(provider="fake", model="configured-model"))

    count = manager.plan(
        project.id,
        project.title,
        project.description,
        TaskService(EventService()),
        EventService(),
        session,
    )

    assert count == 2
    assert len(provider.calls) == 1
    assert provider.calls[0]["model"] == "configured-model"
    assert provider.calls[0]["prompt"] == manager._build_prompt(project.title, project.description)
    assert session.query(Task).count() == 2
    assert session.scalar(
        select(Event).where(Event.event_name == "manager.planning_completed")
    ) is not None
