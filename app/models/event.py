import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models._common import new_uuid, timestamp_from_iso, timestamp_to_iso, utc_now
from app.models.database import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.task import Task


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_name: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    project: Mapped["Project"] = relationship(back_populates="events")
    task: Mapped["Task | None"] = relationship(back_populates="events")

    def __init__(self, **kwargs: object) -> None:
        payload = kwargs.get("payload")
        if isinstance(payload, (dict, list)):
            kwargs["payload"] = json.dumps(payload)
        super().__init__(**kwargs)

    @property
    def payload_dict(self) -> dict[str, Any]:
        parsed = json.loads(self.payload)
        if not isinstance(parsed, dict):
            raise ValueError("Event payload must be a JSON object.")
        return parsed

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id, "project_id": self.project_id, "task_id": self.task_id,
            "event_name": self.event_name, "payload": self.payload_dict,
            "created_at": timestamp_to_iso(self.created_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Event":
        return cls(
            id=data["id"], project_id=data["project_id"], task_id=data.get("task_id"),
            event_name=data["event_name"], payload=data["payload"],
            created_at=timestamp_from_iso(data["created_at"]),
        )
