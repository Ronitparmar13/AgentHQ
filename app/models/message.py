from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models._common import new_uuid, timestamp_from_iso, timestamp_to_iso, utc_now
from app.models.database import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.task import Task


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sender_role: Mapped[str] = mapped_column(String(100), nullable=False)
    message_type: Mapped[str] = mapped_column(String(100), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    project: Mapped["Project"] = relationship(back_populates="messages")
    task: Mapped["Task | None"] = relationship(back_populates="messages")

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id, "project_id": self.project_id, "task_id": self.task_id,
            "sender_role": self.sender_role, "message_type": self.message_type,
            "body": self.body, "created_at": timestamp_to_iso(self.created_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Message":
        return cls(
            id=data["id"], project_id=data["project_id"], task_id=data.get("task_id"),
            sender_role=data["sender_role"], message_type=data["message_type"],
            body=data["body"], created_at=timestamp_from_iso(data["created_at"]),
        )
