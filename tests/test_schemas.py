import pytest
from pydantic import ValidationError

from app.schemas import CreateProjectRequest, ProjectPlan


def valid_plan() -> dict[str, object]:
    return {
        "tasks": [
            {
                "local_id": "TASK-1",
                "title": "Design",
                "description": "Create a design",
                "assigned_role": "designer",
                "priority": "high",
                "dependencies": [],
            }
        ]
    }


def test_project_plan_accepts_valid_roles_and_dependencies() -> None:
    plan = ProjectPlan.model_validate(valid_plan())
    assert plan.tasks[0].assigned_role.value == "designer"


@pytest.mark.parametrize(
    "payload, message",
    [({"tasks": []}, "at least one task"), ({"tasks": [{**valid_plan()["tasks"][0], "dependencies": ["MISSING"]}]}, "unknown dependency")],
)
def test_project_plan_rejects_empty_and_unknown_dependencies(
    payload: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        ProjectPlan.model_validate(payload)


def test_project_plan_rejects_invalid_agent_role() -> None:
    payload = valid_plan()
    payload["tasks"][0]["assigned_role"] = "invented"  # type: ignore[index]
    with pytest.raises(ValidationError):
        ProjectPlan.model_validate(payload)


@pytest.mark.parametrize(
    "title, description, valid",
    [
        ("x", "d", True),
        ("x" * 200, "d" * 5000, True),
        ("", "d", False),
        ("x" * 201, "d", False),
        ("x", "", False),
        ("x", "d" * 5001, False),
    ],
)
def test_create_project_request_length_boundaries(
    title: str, description: str, valid: bool
) -> None:
    if valid:
        assert CreateProjectRequest(title=title, description=description).title == title
    else:
        with pytest.raises(ValidationError):
            CreateProjectRequest(title=title, description=description)
