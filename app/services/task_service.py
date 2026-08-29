"""Task lifecycle and dependency graph operations."""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.constants import AgentRole, EventName, TASK_TRANSITIONS, TaskPriority, TaskStatus
from app.exceptions import InvalidTransitionError, NotFoundError
from app.models import Project, Task, TaskDependency
from app.services.event_service import EventService


class TaskService:
    def __init__(self, event_service: EventService | None = None) -> None:
        self._event_service = event_service or EventService()

    def create_task(
        self,
        session: Session,
        project_id: str,
        title: str,
        description: str | None,
        assigned_role: AgentRole,
        priority: TaskPriority,
        *,
        defer_readiness: bool = False,
    ) -> Task:
        self._get_project(session, project_id)
        role = AgentRole(assigned_role)
        task_priority = TaskPriority(priority)
        task = Task(
            project_id=project_id,
            title=title,
            description=description,
            assigned_role=role,
            priority=task_priority,
            status=TaskStatus.backlog,
        )
        session.add(task)
        session.flush()
        self._event_service.record(
            session,
            project_id,
            EventName.TASK_CREATED,
            {"project_id": project_id, "task_id": task.id, "title": task.title},
            task_id=task.id,
        )
        if not defer_readiness:
            self._promote_if_unblocked(session, task)
        return task

    def get_task(self, session: Session, project_id: str, task_id: str) -> Task:
        task = session.scalar(
            select(Task).where(Task.id == task_id, Task.project_id == project_id)
        )
        if task is None:
            raise NotFoundError(f"Task '{task_id}' not found in project '{project_id}'.")
        return task

    def list_tasks(self, session: Session, project_id: str) -> list[Task]:
        self._get_project(session, project_id)
        return list(
            session.scalars(
                select(Task).where(Task.project_id == project_id).order_by(Task.created_at.asc())
            )
        )

    def update_task_status(
        self,
        session: Session,
        project_id: str,
        task_id: str,
        new_status: TaskStatus,
    ) -> Task:
        task = self.get_task(session, project_id, task_id)
        target = TaskStatus(new_status)
        current = TaskStatus(task.status)
        if target not in TASK_TRANSITIONS[current]:
            raise InvalidTransitionError(task.id, current.value, target.value)
        try:
            self._set_status(session, task, target)
            if target is TaskStatus.done:
                self.evaluate_dependents(session, project_id, task.id)
            session.commit()
            return task
        except Exception:
            session.rollback()
            raise

    def evaluate_dependents(
        self, session: Session, project_id: str, completed_task_id: str
    ) -> list[Task]:
        dependent_ids = session.scalars(
            select(TaskDependency.dependent_task_id).where(
                TaskDependency.project_id == project_id,
                TaskDependency.prerequisite_task_id == completed_task_id,
            )
        ).all()
        promoted: list[Task] = []
        for dependent_id in dependent_ids:
            task = self.get_task(session, project_id, dependent_id)
            if self._promote_if_unblocked(session, task):
                promoted.append(task)
        return promoted

    def create_task_dependency(
        self,
        session: Session,
        project_id: str,
        prerequisite_id: str,
        dependent_id: str,
    ) -> TaskDependency:
        self.get_task(session, project_id, prerequisite_id)
        self.get_task(session, project_id, dependent_id)
        if prerequisite_id == dependent_id:
            raise ValueError("A task cannot depend on itself.")
        existing = session.scalar(
            select(TaskDependency).where(
                TaskDependency.project_id == project_id,
                TaskDependency.prerequisite_task_id == prerequisite_id,
                TaskDependency.dependent_task_id == dependent_id,
            )
        )
        if existing is not None:
            raise ValueError("Task dependency already exists.")
        creates_cycle, path = self._would_create_cycle(
            session, project_id, prerequisite_id, dependent_id
        )
        if creates_cycle:
            raise ValueError(f"Task dependency would create a cycle: {' -> '.join(path)}")
        edge = TaskDependency(
            project_id=project_id,
            prerequisite_task_id=prerequisite_id,
            dependent_task_id=dependent_id,
        )
        session.add(edge)
        session.flush()
        return edge

    def get_task_dependencies(
        self, session: Session, project_id: str, task_id: str
    ) -> dict[str, list[dict[str, object]]]:
        self.get_task(session, project_id, task_id)
        prerequisites = list(
            session.scalars(
                select(Task)
                .join(
                    TaskDependency,
                    Task.id == TaskDependency.prerequisite_task_id,
                )
                .where(
                    TaskDependency.project_id == project_id,
                    TaskDependency.dependent_task_id == task_id,
                )
            )
        )
        dependents = list(
            session.scalars(
                select(Task)
                .join(TaskDependency, Task.id == TaskDependency.dependent_task_id)
                .where(
                    TaskDependency.project_id == project_id,
                    TaskDependency.prerequisite_task_id == task_id,
                )
            )
        )
        return {
            "prerequisites": [task.to_dict() for task in prerequisites],
            "dependents": [task.to_dict() for task in dependents],
        }

    def promote_deferred_tasks(self, session: Session, tasks: Iterable[Task]) -> None:
        for task in tasks:
            self._promote_if_unblocked(session, task)

    def _promote_if_unblocked(self, session: Session, task: Task) -> bool:
        if TaskStatus(task.status) is not TaskStatus.backlog:
            return False
        prerequisite_statuses = session.scalars(
            select(Task.status)
            .join(
                TaskDependency,
                Task.id == TaskDependency.prerequisite_task_id,
            )
            .where(
                TaskDependency.project_id == task.project_id,
                TaskDependency.dependent_task_id == task.id,
            )
        ).all()
        if any(TaskStatus(status) is not TaskStatus.done for status in prerequisite_statuses):
            return False
        self._set_status(session, task, TaskStatus.ready)
        return True

    def _set_status(self, session: Session, task: Task, target: TaskStatus) -> None:
        previous = task.status
        task.status = target.value
        session.flush()
        self._event_service.record(
            session,
            task.project_id,
            EventName.TASK_STATUS_CHANGED,
            {
                "task_id": task.id,
                "project_id": task.project_id,
                "previous_status": previous,
                "new_status": target.value,
            },
            task_id=task.id,
        )

    @staticmethod
    def _would_create_cycle(
        session: Session,
        project_id: str,
        prerequisite_id: str,
        dependent_id: str,
    ) -> tuple[bool, list[str]]:
        edges = session.scalars(
            select(TaskDependency).where(TaskDependency.project_id == project_id)
        ).all()
        adjacency: dict[str, set[str]] = {}
        for edge in edges:
            adjacency.setdefault(edge.prerequisite_task_id, set()).add(edge.dependent_task_id)
        visited: set[str] = set()
        path: list[str] = []

        def dfs(node: str) -> bool:
            if node == prerequisite_id:
                return True
            if node in visited:
                return False
            visited.add(node)
            path.append(node)
            for neighbour in adjacency.get(node, set()):
                if dfs(neighbour):
                    return True
            path.pop()
            return False

        if dfs(dependent_id):
            return True, path + [prerequisite_id]
        return False, []

    @staticmethod
    def _get_project(session: Session, project_id: str) -> Project:
        project = session.get(Project, project_id)
        if project is None:
            raise NotFoundError(f"Project '{project_id}' not found.")
        return project
