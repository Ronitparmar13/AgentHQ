from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.constants import AgentRole, ProjectStatus, TaskPriority, TaskStatus
from app.models import Event, Message, Project, Task, TaskDependency


def project() -> Project:
    return Project(title="Phase 1A", description="Persistence foundation")


def task(project_id: str, title: str = "Build model") -> Task:
    return Task(
        project_id=project_id,
        title=title,
        description="Model work",
        assigned_role=AgentRole.backend,
        priority=TaskPriority.high,
        status=TaskStatus.backlog,
    )


def test_project_defaults_use_uuid4_utc_and_draft_status(session: Session) -> None:
    item = project()
    session.add(item)
    session.flush()

    assert UUID(item.id).version == 4
    assert item.status == ProjectStatus.draft.value
    assert item.created_at.tzinfo is not None
    assert item.updated_at.tzinfo is not None


def test_relationships_and_dependency_edge_directions(session: Session) -> None:
    item = project()
    session.add(item)
    session.flush()
    prerequisite = task(item.id, "Design")
    dependent = task(item.id, "Implement")
    session.add_all([prerequisite, dependent])
    session.flush()
    edge = TaskDependency(
        project_id=item.id,
        prerequisite_task_id=prerequisite.id,
        dependent_task_id=dependent.id,
    )
    session.add(edge)
    session.flush()

    assert item.tasks == [prerequisite, dependent]
    assert prerequisite.dependent_edges == [edge]
    assert dependent.prerequisite_edges == [edge]
    assert edge.prerequisite_task is prerequisite
    assert edge.dependent_task is dependent


def test_task_dependency_is_unique_and_must_belong_to_the_same_project(session: Session) -> None:
    first_project = project()
    second_project = Project(title="Other", description="Other project")
    session.add_all([first_project, second_project])
    session.flush()
    first = task(first_project.id, "First")
    second = task(first_project.id, "Second")
    outside = task(second_project.id, "Outside")
    session.add_all([first, second, outside])
    session.flush()
    session.add(TaskDependency(
        project_id=first_project.id,
        prerequisite_task_id=first.id,
        dependent_task_id=second.id,
    ))
    session.commit()
    session.add(TaskDependency(
        project_id=first_project.id,
        prerequisite_task_id=first.id,
        dependent_task_id=second.id,
    ))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    session.add(TaskDependency(
        project_id=first_project.id,
        prerequisite_task_id=first.id,
        dependent_task_id=outside.id,
    ))
    with pytest.raises(IntegrityError):
        session.flush()


def test_status_role_and_priority_constraints_reject_invalid_values(session: Session) -> None:
    item = project()
    session.add(item)
    session.flush()
    invalid = Task(
        project_id=item.id, title="Invalid", description=None,
        assigned_role="invented", priority="urgent", status="unknown",
    )
    session.add(invalid)
    with pytest.raises(IntegrityError):
        session.flush()


def test_project_cascade_deletes_all_children(session: Session) -> None:
    item = project()
    session.add(item)
    session.flush()
    first = task(item.id, "First")
    second = task(item.id, "Second")
    session.add_all([first, second])
    session.flush()
    session.add_all([
        TaskDependency(project_id=item.id, prerequisite_task_id=first.id, dependent_task_id=second.id),
        Event(project_id=item.id, task_id=first.id, event_name="task.created", payload={"task": first.id}),
        Message(project_id=item.id, task_id=second.id, sender_role="manager", message_type="task_assignment", body="Work"),
    ])
    session.commit()

    session.delete(item)
    session.commit()
    assert session.query(Project).count() == 0
    assert session.query(Task).count() == 0
    assert session.query(TaskDependency).count() == 0
    assert session.query(Event).count() == 0
    assert session.query(Message).count() == 0


@pytest.mark.parametrize(
    "factory",
    [
        lambda project_id, task_id: Project(id="123e4567-e89b-42d3-a456-426614174000", title="P", description="D", status=ProjectStatus.draft),
        lambda project_id, task_id: Task(id="123e4567-e89b-42d3-a456-426614174001", project_id=project_id, title="T", description=None, assigned_role=AgentRole.qa, priority=TaskPriority.medium, status=TaskStatus.ready),
        lambda project_id, task_id: TaskDependency(id="123e4567-e89b-42d3-a456-426614174002", project_id=project_id, prerequisite_task_id=task_id, dependent_task_id=task_id),
        lambda project_id, task_id: Event(id="123e4567-e89b-42d3-a456-426614174003", project_id=project_id, task_id=task_id, event_name="task.created", payload={"value": 1}),
        lambda project_id, task_id: Message(id="123e4567-e89b-42d3-a456-426614174004", project_id=project_id, task_id=task_id, sender_role="qa", message_type="review", body="Looks good"),
    ],
)
def test_model_serialization_round_trip(factory, session: Session) -> None:
    item = project()
    session.add(item)
    session.flush()
    db_task = task(item.id)
    session.add(db_task)
    session.flush()
    model = factory(item.id, db_task.id)
    if isinstance(model, Project):
        model.created_at = item.created_at
        model.updated_at = item.updated_at
    session.add(model)
    session.flush()

    reconstructed = type(model).from_dict(model.to_dict())
    assert reconstructed.to_dict() == model.to_dict()
