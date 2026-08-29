import pytest
from sqlalchemy.orm import Session

from app.constants import AgentRole, TaskPriority, TaskStatus
from app.exceptions import InvalidTransitionError, NotFoundError
from app.models import Project, Task, TaskDependency
from app.services.event_service import EventService
from app.services.task_service import TaskService


def project(session: Session) -> Project:
    item = Project(title="Project", description="Description")
    session.add(item)
    session.commit()
    return item


def create_task(service: TaskService, session: Session, project_id: str, title: str, *, deferred: bool = False) -> Task:
    return service.create_task(
        session, project_id, title, "Description", AgentRole.backend, TaskPriority.medium,
        defer_readiness=deferred,
    )


def advance_to_done(service: TaskService, session: Session, task: Task) -> None:
    service.update_task_status(session, task.project_id, task.id, TaskStatus.in_progress)
    service.update_task_status(session, task.project_id, task.id, TaskStatus.review)
    service.update_task_status(session, task.project_id, task.id, TaskStatus.done)


def test_task_creation_is_ready_and_records_activity(session: Session) -> None:
    item = project(session)
    service = TaskService()
    task = create_task(service, session, item.id, "Build")

    assert task.status == TaskStatus.ready.value
    assert {event.event_name for event in item.events} == {"task.created", "task.status_changed"}


def test_task_transitions_and_invalid_transition(session: Session) -> None:
    item = project(session)
    service = TaskService()
    task = create_task(service, session, item.id, "Build")
    service.update_task_status(session, item.id, task.id, TaskStatus.in_progress)
    assert task.status == TaskStatus.in_progress.value

    with pytest.raises(InvalidTransitionError):
        service.update_task_status(session, item.id, task.id, TaskStatus.done)
    session.refresh(task)
    assert task.status == TaskStatus.in_progress.value


def test_dependencies_reject_duplicates_self_and_cycles(session: Session) -> None:
    item = project(session)
    service = TaskService()
    first = create_task(service, session, item.id, "First", deferred=True)
    second = create_task(service, session, item.id, "Second", deferred=True)
    third = create_task(service, session, item.id, "Third", deferred=True)
    service.create_task_dependency(session, item.id, first.id, second.id)
    service.create_task_dependency(session, item.id, second.id, third.id)
    with pytest.raises(ValueError, match="already exists"):
        service.create_task_dependency(session, item.id, first.id, second.id)
    with pytest.raises(ValueError, match="itself"):
        service.create_task_dependency(session, item.id, first.id, first.id)
    with pytest.raises(ValueError, match="cycle"):
        service.create_task_dependency(session, item.id, third.id, first.id)
    assert session.query(TaskDependency).count() == 2


def test_dependencies_cannot_cross_projects_and_can_be_retrieved(session: Session) -> None:
    item = project(session)
    other = project(session)
    service = TaskService()
    prerequisite = create_task(service, session, item.id, "Prerequisite", deferred=True)
    dependent = create_task(service, session, item.id, "Dependent", deferred=True)
    outside = create_task(service, session, other.id, "Outside", deferred=True)
    service.create_task_dependency(session, item.id, prerequisite.id, dependent.id)
    with pytest.raises(NotFoundError):
        service.create_task_dependency(session, item.id, prerequisite.id, outside.id)

    dependencies = service.get_task_dependencies(session, item.id, dependent.id)
    assert [task["id"] for task in dependencies["prerequisites"]] == [prerequisite.id]
    assert service.get_task_dependencies(session, item.id, prerequisite.id)["dependents"][0]["id"] == dependent.id


def test_done_promotes_only_dependents_with_all_prerequisites(session: Session) -> None:
    item = project(session)
    service = TaskService()
    first = create_task(service, session, item.id, "First", deferred=True)
    second = create_task(service, session, item.id, "Second", deferred=True)
    dependent = create_task(service, session, item.id, "Dependent", deferred=True)
    service.create_task_dependency(session, item.id, first.id, dependent.id)
    service.create_task_dependency(session, item.id, second.id, dependent.id)
    service.promote_deferred_tasks(session, [first, second, dependent])
    session.commit()

    advance_to_done(service, session, first)
    assert dependent.status == TaskStatus.backlog.value
    advance_to_done(service, session, second)
    assert dependent.status == TaskStatus.ready.value


def test_task_status_update_is_atomic_when_event_recording_fails(session: Session) -> None:
    item = project(session)
    task = Task(
        project_id=item.id, title="Build", description=None, assigned_role=AgentRole.backend,
        priority=TaskPriority.medium, status=TaskStatus.ready,
    )
    session.add(task)
    session.commit()

    class FailingEvents(EventService):
        def record(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("event failure")

    service = TaskService(FailingEvents())
    with pytest.raises(RuntimeError, match="event failure"):
        service.update_task_status(session, item.id, task.id, TaskStatus.in_progress)
    session.refresh(task)
    assert task.status == TaskStatus.ready.value
