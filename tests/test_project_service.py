from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.manager import ManagerAgent
from app.constants import AgentRole, ProjectStatus, TaskPriority
from app.exceptions import ConflictError, InvalidTransitionError, LLMProviderError
from app.models import Event, Project, Task
from app.schemas import ModelConfig
from app.services.project_service import ProjectService


def create_project(service: ProjectService, session: Session, title: str = "Project") -> Project:
    return service.create_project(session, title, "Description")


def successful_manager() -> ManagerAgent:
    router = MagicMock()
    router.complete.return_value = """{
      "tasks": [{"local_id": "TASK-1", "title": "Build", "description": "Build it", "assigned_role": "backend", "priority": "high", "dependencies": []}]
    }"""
    return ManagerAgent(router, ModelConfig(provider="mock", model="model"))


def test_project_creation_event_ordering_and_status_transitions(session: Session) -> None:
    service = ProjectService()
    first = create_project(service, session, "First")
    second = create_project(service, session, "Second")
    assert [project.title for project in service.list_projects(session)] == ["Second", "First"]
    assert first.status == ProjectStatus.draft.value
    assert session.scalar(select(Event).where(Event.project_id == first.id, Event.event_name == "project.created"))

    service.update_project_status(session, first.id, ProjectStatus.planning)
    assert first.status == ProjectStatus.planning.value
    with pytest.raises(InvalidTransitionError):
        service.update_project_status(session, first.id, ProjectStatus.delivered)


def test_successful_planning_is_atomic_and_marks_project_in_progress(session: Session) -> None:
    service = ProjectService()
    project = create_project(service, session)
    service.trigger_planning(session, project.id, successful_manager())
    session.refresh(project)

    assert project.status == ProjectStatus.in_progress.value
    assert session.query(Task).filter_by(project_id=project.id).count() == 1
    names = {event.event_name for event in session.scalars(select(Event).where(Event.project_id == project.id))}
    assert {"manager.planning_started", "manager.planning_completed"}.issubset(names)


def test_planning_failure_rolls_back_tasks_then_records_blocked_failure(session: Session) -> None:
    service = ProjectService()
    project = create_project(service, session)
    invalid = successful_manager()
    invalid.llm_router.complete.return_value = "not valid json"
    with pytest.raises(ValidationError):
        service.trigger_planning(session, project.id, invalid)

    session.refresh(project)
    assert project.status == ProjectStatus.blocked.value
    assert session.query(Task).filter_by(project_id=project.id).count() == 0
    names = [event.event_name for event in session.scalars(select(Event).where(Event.project_id == project.id))]
    assert "manager.planning_failed" in names


def test_provider_planning_failure_records_safe_blocked_outcome(session: Session) -> None:
    service = ProjectService()
    project = create_project(service, session)
    manager = successful_manager()
    manager.llm_router.complete.side_effect = LLMProviderError("mock", "network_error", "network details")
    with pytest.raises(LLMProviderError):
        service.trigger_planning(session, project.id, manager)

    session.refresh(project)
    failure = session.scalar(
        select(Event).where(Event.project_id == project.id, Event.event_name == "manager.planning_failed")
    )
    assert project.status == ProjectStatus.blocked.value
    assert "network details" not in failure.payload


def test_planning_rolls_back_partial_task_persistence(session: Session) -> None:
    service = ProjectService()
    project = create_project(service, session)

    class PartiallyFailingManager:
        def plan(self, **kwargs):  # type: ignore[no-untyped-def]
            kwargs["task_service"].create_task(
                kwargs["session"], kwargs["project_id"], "Partial", "D",
                AgentRole.backend, TaskPriority.low, defer_readiness=True,
            )
            raise RuntimeError("planned task persistence failed")

    with pytest.raises(RuntimeError, match="planned task persistence failed"):
        service.trigger_planning(session, project.id, PartiallyFailingManager())
    assert session.query(Task).filter_by(project_id=project.id).count() == 0
    session.refresh(project)
    assert project.status == ProjectStatus.blocked.value


def test_planning_conflict_is_rejected_without_a_second_run(session: Session) -> None:
    service = ProjectService()
    project = create_project(service, session)
    service.update_project_status(session, project.id, ProjectStatus.planning)
    with pytest.raises(ConflictError):
        service.trigger_planning(session, project.id, successful_manager())
