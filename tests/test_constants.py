from app.constants import (
    AgentRole,
    PROJECT_TRANSITIONS,
    TASK_TRANSITIONS,
    ProjectStatus,
    TaskPriority,
    TaskStatus,
)


def test_domain_enumerations_have_approved_values() -> None:
    assert [role.value for role in AgentRole] == [
        "manager", "designer", "frontend", "backend", "qa", "utility",
    ]
    assert [status.value for status in ProjectStatus] == [
        "draft", "planning", "in_progress", "review", "blocked", "delivered", "cancelled",
    ]
    assert [status.value for status in TaskStatus] == [
        "backlog", "ready", "in_progress", "review", "blocked", "rework", "done",
    ]
    assert [priority.value for priority in TaskPriority] == ["low", "medium", "high"]


def test_approved_state_machine_definitions() -> None:
    assert TASK_TRANSITIONS[TaskStatus.backlog] == {TaskStatus.ready}
    assert TASK_TRANSITIONS[TaskStatus.review] == {TaskStatus.done, TaskStatus.rework}
    assert TASK_TRANSITIONS[TaskStatus.done] == set()
    assert PROJECT_TRANSITIONS[ProjectStatus.draft] == {
        ProjectStatus.planning, ProjectStatus.cancelled,
    }
    assert PROJECT_TRANSITIONS[ProjectStatus.delivered] == set()
