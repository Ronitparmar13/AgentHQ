from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models._common import new_uuid, timestamp_from_iso, timestamp_to_iso, utc_now
from app.models.database import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.task import Task


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "prerequisite_task_id", "dependent_task_id", name="uq_task_dependency_edge"
        ),
        ForeignKeyConstraint(
            ["project_id", "prerequisite_task_id"],
            ["tasks.project_id", "tasks.id"],
            ondelete="CASCADE",
            name="fk_dependency_prerequisite_in_project",
        ),
        ForeignKeyConstraint(
            ["project_id", "dependent_task_id"],
            ["tasks.project_id", "tasks.id"],
            ondelete="CASCADE",
            name="fk_dependency_dependent_in_project",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prerequisite_task_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    dependent_task_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    project: Mapped["Project"] = relationship(back_populates="dependencies")
    prerequisite_task: Mapped["Task"] = relationship(
        back_populates="dependent_edges", foreign_keys=[prerequisite_task_id]
    )
    dependent_task: Mapped["Task"] = relationship(
        back_populates="prerequisite_edges", foreign_keys=[dependent_task_id]
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "prerequisite_task_id": self.prerequisite_task_id,
            "dependent_task_id": self.dependent_task_id,
            "created_at": timestamp_to_iso(self.created_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "TaskDependency":
        return cls(
            id=data["id"], project_id=data["project_id"],
            prerequisite_task_id=data["prerequisite_task_id"],
            dependent_task_id=data["dependent_task_id"],
            created_at=timestamp_from_iso(data["created_at"]),
        )
