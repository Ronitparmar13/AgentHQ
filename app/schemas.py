"""Validated boundary schemas for plans, agents, and API inputs."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.constants import AgentRole, ProjectStatus, TaskPriority, TaskStatus


class PlanTask(BaseModel):
    local_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=255)
    description: str
    assigned_role: AgentRole
    priority: TaskPriority
    dependencies: list[str] = Field(default_factory=list)


class ProjectPlan(BaseModel):
    tasks: list[PlanTask]

    @model_validator(mode="after")
    def validate_plan(self) -> "ProjectPlan":
        if not self.tasks:
            raise ValueError("ProjectPlan must contain at least one task")
        local_ids = {task.local_id for task in self.tasks}
        if len(local_ids) != len(self.tasks):
            raise ValueError("ProjectPlan task local_ids must be unique")
        for task in self.tasks:
            for dependency in task.dependencies:
                if dependency not in local_ids:
                    raise ValueError(
                        f"Task '{task.local_id}' references unknown dependency '{dependency}'"
                    )
        return self


class ModelConfig(BaseModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)


class AgentResult(BaseModel):
    status: Literal["success", "failure", "not_implemented"]
    output: dict
    error: str | None = None


class CreateProjectRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)

    @field_validator("title", "description")
    @classmethod
    def reject_whitespace_only(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be blank")
        return value


class UpdateProjectStatusRequest(BaseModel):
    status: ProjectStatus


class UpdateTaskStatusRequest(BaseModel):
    status: TaskStatus
