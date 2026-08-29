from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import ProjectStatus
from app.models._common import enum_value, new_uuid, timestamp_from_iso, timestamp_to_iso, utc_now
from app.models.database import Base

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.message import Message
    from app.models.task import Task
    from app.models.task_dependency import TaskDependency


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'planning', 'in_progress', 'review', 'blocked', 'delivered', 'cancelled')",
            name="ck_projects_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ProjectStatus.draft.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    tasks: Mapped[list["Task"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    events: Mapped[list["Event"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    dependencies: Mapped[list["TaskDependency"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )

    def __init__(self, **kwargs: object) -> None:
        if "status" in kwargs:
            kwargs["status"] = enum_value(kwargs["status"])
        super().__init__(**kwargs)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "created_at": timestamp_to_iso(self.created_at),
            "updated_at": timestamp_to_iso(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Project":
        return cls(
            id=data["id"], title=data["title"], description=data["description"],
            status=data["status"], created_at=timestamp_from_iso(data["created_at"]),
            updated_at=timestamp_from_iso(data["updated_at"]),
        )
