"""Project lifecycle and atomic Manager planning orchestration."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import EventName, PROJECT_TRANSITIONS, ProjectStatus
from app.exceptions import ConflictError, InvalidTransitionError, NotFoundError
from app.models import Project
from app.services.event_service import EventService
from app.services.task_service import TaskService


class ProjectService:
    def __init__(
        self,
        event_service: EventService | None = None,
        task_service: TaskService | None = None,
    ) -> None:
        self._event_service = event_service or EventService()
        self._task_service = task_service or TaskService(self._event_service)

    def create_project(self, session: Session, title: str, description: str) -> Project:
        self._validate_project_input(title, description)
        try:
            project = Project(title=title.strip(), description=description.strip())
            session.add(project)
            session.flush()
            self._event_service.record(
                session,
                project.id,
                EventName.PROJECT_CREATED,
                {"project_id": project.id, "title": project.title, "status": project.status},
            )
            session.commit()
            return project
        except Exception:
            session.rollback()
            raise

    def get_project(self, session: Session, project_id: str) -> Project:
        project = session.get(Project, project_id)
        if project is None:
            raise NotFoundError(f"Project '{project_id}' not found.")
        return project

    def list_projects(self, session: Session) -> list[Project]:
        return list(session.scalars(select(Project).order_by(Project.created_at.desc(), Project.id.desc())))

    def update_project_status(
        self, session: Session, project_id: str, new_status: ProjectStatus
    ) -> Project:
        project = self.get_project(session, project_id)
        target = ProjectStatus(new_status)
        current = ProjectStatus(project.status)
        if target not in PROJECT_TRANSITIONS[current]:
            raise InvalidTransitionError(project.id, current.value, target.value)
        try:
            self._set_status(session, project, target)
            session.commit()
            return project
        except Exception:
            session.rollback()
            raise

    def trigger_planning(self, session: Session, project_id: str, manager_agent: object) -> None:
        project = self.get_project(session, project_id)
        current = ProjectStatus(project.status)
        if current in {ProjectStatus.planning, ProjectStatus.in_progress}:
            raise ConflictError(f"Project '{project_id}' is already being planned.")
        if ProjectStatus.planning not in PROJECT_TRANSITIONS[current]:
            raise InvalidTransitionError(project.id, current.value, ProjectStatus.planning.value)
        try:
            self._set_status(session, project, ProjectStatus.planning)
            self._event_service.record(
                session,
                project.id,
                EventName.MANAGER_PLANNING_STARTED,
                {"project_id": project.id},
            )
            manager_agent.plan(
                project_id=project.id,
                title=project.title,
                description=project.description,
                task_service=self._task_service,
                event_service=self._event_service,
                session=session,
            )
            self._set_status(session, project, ProjectStatus.in_progress)
            session.commit()
        except Exception:
            session.rollback()
            self._persist_planning_failure(session, project_id)
            raise

    def _persist_planning_failure(self, session: Session, project_id: str) -> None:
        """Persist only the intended blocked state and safe failure event."""
        try:
            project = self.get_project(session, project_id)
            self._set_status(session, project, ProjectStatus.blocked)
            self._event_service.record(
                session,
                project.id,
                EventName.MANAGER_PLANNING_FAILED,
                {
                    "project_id": project.id,
                    "reason": "Manager planning failed. Review the project requirements and retry.",
                },
            )
            session.commit()
        except Exception:
            session.rollback()
            raise

    def _set_status(self, session: Session, project: Project, target: ProjectStatus) -> None:
        previous = project.status
        project.status = target.value
        session.flush()
        self._event_service.record(
            session,
            project.id,
            EventName.PROJECT_STATUS_CHANGED,
            {
                "project_id": project.id,
                "previous_status": previous,
                "new_status": target.value,
            },
        )

    @staticmethod
    def _validate_project_input(title: str, description: str) -> None:
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValueError("Project title must be between 1 and 200 characters.")
        if not isinstance(description, str) or not description.strip() or len(description) > 5000:
            raise ValueError("Project description must be between 1 and 5000 characters.")
