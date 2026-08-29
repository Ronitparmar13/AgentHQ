"""Persistent, safe activity event recording."""

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Event

_SECRET_PATTERN = re.compile(r"(?i)(key|token|secret|password)")
_MAX_REDACT_DEPTH = 3


class EventService:
    def record(
        self,
        session: Session,
        project_id: str,
        event_name: str,
        payload: dict[str, Any],
        task_id: str | None = None,
    ) -> Event:
        """Add a redacted, JSON-serializable event to the current transaction."""
        try:
            redacted_payload = self._redact_secrets(payload)
            serialized_payload = json.dumps(redacted_payload)
            event = Event(
                project_id=project_id,
                task_id=task_id,
                event_name=event_name,
                payload=serialized_payload,
            )
            session.add(event)
            session.flush()
            return event
        except (TypeError, ValueError, SQLAlchemyError) as exc:
            raise RuntimeError(
                f"Could not record event '{event_name}' for project '{project_id}'."
            ) from exc

    def list_events(self, session: Session, project_id: str) -> list[Event]:
        return list(
            session.scalars(
                select(Event)
                .where(Event.project_id == project_id)
                .order_by(Event.created_at.asc(), Event.id.asc())
            )
        )

    @classmethod
    def _redact_secrets(cls, payload: dict[str, Any], depth: int = 1) -> dict[str, Any]:
        """Return a non-destructive redaction through the approved depth limit."""
        if depth > _MAX_REDACT_DEPTH:
            return payload
        result: dict[str, Any] = {}
        for key, value in payload.items():
            if _SECRET_PATTERN.search(key):
                result[key] = "[REDACTED]"
            elif isinstance(value, dict) and depth < _MAX_REDACT_DEPTH:
                result[key] = cls._redact_secrets(value, depth + 1)
            else:
                result[key] = value
        return result
