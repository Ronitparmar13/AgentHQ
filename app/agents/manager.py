"""Manager planning agent: LLM output in, validated task plan out."""

from typing import TYPE_CHECKING

from app.constants import AgentRole, EventName
from app.agents.base import BaseAgent
from app.llm.router import LLMRouter
from app.schemas import AgentResult, ModelConfig, ProjectPlan

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models import Task
    from app.services.event_service import EventService
    from app.services.task_service import TaskService


class ManagerAgent(BaseAgent):
    name = "Manager"
    role = AgentRole.manager

    def __init__(self, llm_router: LLMRouter, model_config: ModelConfig) -> None:
        self.llm_router = llm_router
        self.model_config = model_config

    def plan(
        self,
        project_id: str,
        title: str,
        description: str,
        task_service: "TaskService",
        event_service: "EventService",
        session: "Session",
    ) -> int:
        """Validate an LLM plan, then delegate all persistence to services."""
        raw_plan = self.llm_router.complete(
            role="MANAGER", prompt=self._build_prompt(title, description)
        )
        plan = ProjectPlan.model_validate_json(raw_plan)
        local_tasks = {}
        for planned_task in plan.tasks:
            local_tasks[planned_task.local_id] = task_service.create_task(
                session=session,
                project_id=project_id,
                title=planned_task.title,
                description=planned_task.description,
                assigned_role=planned_task.assigned_role,
                priority=planned_task.priority,
                defer_readiness=True,
            )
        for planned_task in plan.tasks:
            dependent = local_tasks[planned_task.local_id]
            for prerequisite_local_id in planned_task.dependencies:
                task_service.create_task_dependency(
                    session=session,
                    project_id=project_id,
                    prerequisite_id=local_tasks[prerequisite_local_id].id,
                    dependent_id=dependent.id,
                )
        task_service.promote_deferred_tasks(session, local_tasks.values())
        event_service.record(
            session,
            project_id,
            EventName.MANAGER_PLANNING_COMPLETED,
            {"project_id": project_id, "task_count": len(local_tasks)},
        )
        return len(local_tasks)

    def _build_prompt(self, title: str, description: str) -> str:
        return f"""You are the Manager Agent for AgentHQ.

Your job is to analyze a software project requirement and produce a structured task plan.

Project Title: {title}
Project Description: {description}

Return a JSON object with this exact structure:
{{
  "tasks": [
    {{
      "local_id": "TASK-1",
      "title": "...",
      "description": "...",
      "assigned_role": "<one of: manager|designer|frontend|backend|qa|utility>",
      "priority": "<one of: low|medium|high>",
      "dependencies": ["TASK-N", ...]
    }}
  ]
}}

Rules:
- Return ONLY the JSON object. No explanation, no markdown code fences.
- Every task must have a unique local_id.
- dependencies must reference local_ids from within this same plan.
- assigned_role must be one of the listed values.
- priority must be one of the listed values."""

    def run(self, task: "Task", context: dict) -> AgentResult:
        return AgentResult(
            status="not_implemented",
            output={},
            error="Manager.run() is not used in Phase 1; use plan() instead.",
        )
