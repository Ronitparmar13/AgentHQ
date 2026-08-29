"""Internal helpers shared by model modules."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4


def new_uuid() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


def enum_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def timestamp_to_iso(value: datetime) -> str:
    """Serialize both SQLite-naive and timezone-aware UTC values consistently."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat().replace("+00:00", "Z")


def timestamp_from_iso(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
