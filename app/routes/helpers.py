"""Shared helpers for Flask route blueprints."""

import re
from typing import Any

from flask import jsonify

_UUID4_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def validate_uuid4(value: str, name: str) -> str:
    if not _UUID4_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid {name}: '{value}' is not a valid UUID.")
    return value


def json_error(message: str, code: str, status: int, **extra: Any) -> tuple[Any, int]:
    payload: dict[str, Any] = {"error": message, "code": code}
    payload.update(extra)
    return jsonify(payload), status
