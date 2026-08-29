"""Shared domain enumerations and state-machine definitions."""

from enum import Enum


class AgentRole(str, Enum):
    manager = "manager"
    designer = "designer"
    frontend = "frontend"
    backend = "backend"
    qa = "qa"
    utility = "utility"


class ProjectStatus(str, Enum):
    draft = "draft"
    planning = "planning"
    in_progress = "in_progress"
    review = "review"
    blocked = "blocked"
    delivered = "delivered"
    cancelled = "cancelled"


class TaskStatus(str, Enum):
    backlog = "backlog"
    ready = "ready"
    in_progress = "in_progress"
    review = "review"
    blocked = "blocked"
    rework = "rework"
    done = "done"


class TaskPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class EventName:
    PROJECT_CREATED = "project.created"
    PROJECT_STATUS_CHANGED = "project.status_changed"
    MANAGER_PLANNING_STARTED = "manager.planning_started"
    MANAGER_PLANNING_COMPLETED = "manager.planning_completed"
    MANAGER_PLANNING_FAILED = "manager.planning_failed"
    TASK_CREATED = "task.created"
    TASK_STATUS_CHANGED = "task.status_changed"


TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.backlog: {TaskStatus.ready},
    TaskStatus.ready: {TaskStatus.in_progress},
    TaskStatus.in_progress: {TaskStatus.review, TaskStatus.blocked},
    TaskStatus.review: {TaskStatus.done, TaskStatus.rework},
    TaskStatus.blocked: {TaskStatus.in_progress},
    TaskStatus.rework: {TaskStatus.in_progress, TaskStatus.done},
    TaskStatus.done: set(),
}


PROJECT_TRANSITIONS: dict[ProjectStatus, set[ProjectStatus]] = {
    ProjectStatus.draft: {ProjectStatus.planning, ProjectStatus.cancelled},
    ProjectStatus.planning: {
        ProjectStatus.in_progress,
        ProjectStatus.blocked,
        ProjectStatus.cancelled,
    },
    ProjectStatus.in_progress: {
        ProjectStatus.review,
        ProjectStatus.blocked,
        ProjectStatus.cancelled,
    },
    ProjectStatus.review: {
        ProjectStatus.delivered,
        ProjectStatus.in_progress,
        ProjectStatus.blocked,
    },
    ProjectStatus.blocked: {ProjectStatus.in_progress, ProjectStatus.cancelled},
    ProjectStatus.delivered: set(),
    ProjectStatus.cancelled: set(),
}
