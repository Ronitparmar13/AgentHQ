from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import AgentRole, TaskPriority, TaskStatus
from app.models._common import enum_value, new_uuid, timestamp_from_iso, timestamp_to_iso, utc_now
from app.models.database import Base

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.message import Message
    from app.models.project import Project
    from app.models.task_dependency import TaskDependency


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "assigned_role IN ('manager', 'designer', 'frontend', 'backend', 'qa', 'utility')",
            name="ck_tasks_assigned_role",
        ),
        CheckConstraint("priority IN ('low', 'medium', 'high')", name="ck_tasks_priority"),
        CheckConstraint(
            "status IN ('backlog', 'ready', 'in_progress', 'review', 'blocked', 'rework', 'done')",
            name="ck_tasks_status",
        ),
        UniqueConstraint("project_id", "id", name="uq_tasks_project_id_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_role: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=TaskStatus.backlog.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    project: Mapped["Project"] = relationship(back_populates="tasks")
    prerequisite_edges: Mapped[list["TaskDependency"]] = relationship(
        back_populates="dependent_task",
        foreign_keys="TaskDependency.dependent_task_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    dependent_edges: Mapped[list["TaskDependency"]] = relationship(
        back_populates="prerequisite_task",
        foreign_keys="TaskDependency.prerequisite_task_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    events: Mapped[list["Event"]] = relationship(back_populates="task")
    messages: Mapped[list["Message"]] = relationship(back_populates="task")

    def __init__(self, **kwargs: object) -> None:
        for field in ("assigned_role", "priority", "status"):
            if field in kwargs:
                kwargs[field] = enum_value(kwargs[field])
        super().__init__(**kwargs)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id, "project_id": self.project_id, "title": self.title,
            "description": self.description, "assigned_role": self.assigned_role,
            "priority": self.priority, "status": self.status,
            "created_at": timestamp_to_iso(self.created_at),
            "updated_at": timestamp_to_iso(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Task":
        return cls(
            id=data["id"], project_id=data["project_id"], title=data["title"],
            description=data["description"], assigned_role=data["assigned_role"],
            priority=data["priority"], status=data["status"],
            created_at=timestamp_from_iso(data["created_at"]),
            updated_at=timestamp_from_iso(data["updated_at"]),
        )
