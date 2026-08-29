# Design Document: AgentHQ MVP Phase 1

## Overview

AgentHQ MVP Phase 1 implements the complete, stable foundation for an autonomous AI software company. The user (CEO) submits software projects through a web UI. A Manager Agent backed by a real LLM call analyzes each project, produces a structured `ProjectPlan`, and persists tasks with dependencies in SQLite. All state — projects, tasks, dependencies, events, messages — is stored in the database and exposed through a REST API and Jinja2-rendered UI pages.

Phase 1 deliberately stops short of executing specialist agents, running QA, integrating Graphify, or migrating to PostgreSQL. The goal is a rock-solid foundation with real orchestration: routing, validation, persistence, and event recording all wired together and covered by automated tests.

**Primary deliverable:** A user can submit a project, the Manager LLM produces a plan, tasks appear on the project detail page, and every state transition is reflected accurately in the activity feed — with no fabricated data anywhere.

---

## Architecture

### Component Diagram

```
                        CEO / Browser
                             │
                    HTTP Request/Response
                             │
                    ┌────────▼─────────┐
                    │   Flask App      │
                    │  (app/__init__)  │
                    └────────┬─────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
     ┌────────▼────────┐          ┌─────────▼────────┐
     │  API Blueprint  │          │   UI Blueprint   │
     │ (routes/api.py) │          │ (routes/ui.py)   │
     └────────┬────────┘          └─────────┬────────┘
              │                             │
              │  delegates (no biz logic)   │
              └──────────────┬──────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼───┐  ┌───────▼────┐  ┌─────▼──────┐
     │ Project    │  │  Task      │  │  Event     │
     │ Service    │  │  Service   │  │  Service   │
     └────────┬───┘  └───────┬────┘  └─────┬──────┘
              │              │              │
              └──────────────┼──────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼───┐  ┌───────▼────┐  ┌─────▼──────┐
     │  SQLAlchemy│  │  Manager   │  │  LLM       │
     │  Models    │  │  Agent     │  │  Router    │
     │ (models/)  │  │(agents/)   │  │ (llm/)     │
     └────────┬───┘  └───────┬────┘  └─────┬──────┘
              │              │              │
     ┌────────▼───────────────────┐  ┌─────▼──────┐
     │       SQLite / SQLAlchemy  │  │  LLM       │
     │          (agenthq.db)      │  │  Provider  │
     └────────────────────────────┘  └────────────┘
```

### Layer Separation

| Layer | Module | Flask? | SQLAlchemy Session? | Responsibility |
|---|---|---|---|---|
| Route | `app/routes/` | Yes | No | HTTP boundary: validate input, call services, format response |
| Service | `app/services/` | No | Accepts as param | Business logic, coordinates models, agents, tools |
| Agent | `app/agents/` | No | Accepts as param | LLM reasoning, delegates DB writes to services |
| LLM | `app/llm/` | No | No | Provider abstraction and request routing |
| Model | `app/models/` | No | No | SQLAlchemy schema and ORM definitions |
| Tool | `app/tools/` | No | No | Side effects (filesystem, git) with validation |

### Primary Request Flows

**Flow A: CEO submits project → Manager planning → tasks persisted**

```
POST /api/projects
    │
    ▼ Route: validate CreateProjectRequest (Pydantic)
    │
    ▼ ProjectService.create_project(session, title, description)
        │ → Project row inserted (status=draft)
        │ → EventService.record(project.created)
        │ → returns Project
    │
    ▼ Route: 201 JSON response with project id
    │
    ▼ (Client calls POST /api/projects/<id>/plan)
    │
POST /api/projects/<id>/plan
    │
    ▼ Route: validate project exists, validate status allows planning
    │
    ▼ ProjectService.trigger_planning(session, project_id, manager_agent)
        │ → update project status → planning
        │ → EventService.record(manager.planning_started)
        │ → ManagerAgent.plan(project_id, title, description, session)
              │ → LLMRouter.complete(role="MANAGER", prompt=...)
              │ → raw string returned
              │ → ProjectPlan Pydantic parse
              │    ├─ valid → persist tasks via TaskService.create_task()
              │    │            each task with no deps → immediately set to ready
              │    │          persist deps via TaskService.create_task_dependency()
              │    │          update project status → in_progress
              │    │          EventService.record(manager.planning_completed)
              │    └─ invalid → EventService.record(manager.planning_failed)
              │                 update project status → blocked
    │  (trigger_planning owns commit/rollback — route has no session logic)
    ▼ Route: 200 JSON {"status": "planning_triggered"}
```

**Flow B: CEO patches task status → dependency cascade → events recorded**

```
PATCH /api/projects/<pid>/tasks/<tid>/status
    │
    ▼ Route: validate UUID params, validate UpdateTaskStatusRequest
    │
    ▼ TaskService.update_task_status(session, project_id, task_id, new_status)
        │ → validate transition against TASK_TRANSITIONS map
        │    └─ invalid → raise InvalidTransitionError (→ 422)
        │ → update Task.status
        │ → EventService.record(task.status_changed, {prev, new, task_id, project_id})
        │ → if new_status == done:
        │       TaskService.evaluate_dependents(session, project_id, task_id)
        │           → query TaskDependency where prerequisite_task_id = task_id
        │           → for each dependent: check all prerequisites done
        │           → if all done: update to ready
        │                          EventService.record(task.status_changed, ...)
        │ → commit (all-or-nothing transaction)
    │
    ▼ Route: 200 JSON with updated task
```

---

## Components and Interfaces

### Module Structure

```
app/
├── __init__.py               # Application factory: create_app()
├── config.py                 # AppConfig: reads env vars, exposes typed config
├── exceptions.py             # ConfigurationError, WorkspaceBoundaryError,
│                             #   InvalidTransitionError, LLMProviderError
│
├── agents/
│   ├── __init__.py           # AGENT_REGISTRY dict, registry helpers
│   ├── base.py               # BaseAgent abstract class
│   ├── manager.py            # ManagerAgent: plan() method + prompt builder
│   ├── designer.py           # Stub: returns not_implemented AgentResult
│   ├── frontend.py           # Stub: returns not_implemented AgentResult
│   ├── backend.py            # Stub: returns not_implemented AgentResult
│   ├── qa.py                 # Stub: returns not_implemented AgentResult
│   └── utility.py            # Stub: returns not_implemented AgentResult
│
├── llm/
│   ├── __init__.py           # Exports LLMRouter, PROVIDER_REGISTRY
│   ├── base.py               # BaseLLMProvider abstract class
│   ├── router.py             # LLMRouter: resolves role → provider, validates, delegates
│   ├── config.py             # LLMConfig: loads per-role model config from env
│   └── providers/
│       ├── __init__.py                    # build_provider_registry(): named providers + openai_compatible
│       ├── openai_provider.py             # OpenAIProvider: OpenAI chat completions via httpx
│       ├── anthropic_provider.py          # AnthropicProvider: Anthropic Messages API via httpx
│       ├── gemini_provider.py             # GeminiProvider: Google Gemini generateContent API via httpx
│       └── openai_compatible_provider.py  # OpenAICompatibleProvider: configurable base_url for any OAI-compatible endpoint
│
├── models/
│   ├── __init__.py           # Exports db (SQLAlchemy instance) and all models
│   ├── database.py           # SQLAlchemy engine + session factory; db session managed via Flask g
│   ├── project.py            # Project model
│   ├── task.py               # Task model
│   ├── task_dependency.py    # TaskDependency model
│   ├── event.py              # Event model
│   └── message.py            # Message model
│
├── orchestration/
│   └── __init__.py           # (Reserved for Phase 2 orchestrator; empty in Phase 1)
│
├── routes/
│   ├── __init__.py           # Blueprint imports
│   ├── api.py                # API Blueprint (prefix /api): all REST endpoints
│   ├── ui.py                 # UI Blueprint (no prefix): dashboard, form, detail pages
│   └── helpers.py            # Shared: validate_uuid4(), json_error(), paginate()
│
├── services/
│   ├── __init__.py           # Service exports
│   ├── project_service.py    # ProjectService: create, get, list, status, trigger planning
│   ├── task_service.py       # TaskService: create, get, list, status, deps, cascade
│   └── event_service.py      # EventService: record, list, secret redaction
│
└── tools/
    ├── __init__.py           # Tool exports
    └── filesystem.py         # FilesystemTool: read/write/list with workspace boundary check

templates/
├── base.html                 # Base layout: nav, blocks for title/content
├── dashboard.html            # Project list with status summary
├── project_form.html         # Create project form (JS posts to API)
└── project_detail.html       # Project info, task list, activity feed

static/
├── css/
│   └── main.css              # Minimal stylesheet
└── js/
    └── main.js               # Form submit handler, status PATCH calls

tests/
├── conftest.py               # Fixtures: in-memory DB, test client, mock LLM router
├── test_project_service.py   # Project CRUD, status transitions, event recording
├── test_task_service.py      # Task creation, status transitions, dependency cascade
├── test_event_service.py     # Event recording, secret redaction, listing
├── test_manager_agent.py     # Plan success, plan failure, provider error paths
├── test_llm_router.py        # Role/prompt validation, provider delegation, errors
├── test_dependency_resolution.py  # DAG operations, cycle detection, prerequisite eval
├── test_filesystem_tool.py   # Boundary enforcement, path traversal rejection
└── test_api_routes.py        # HTTP contract tests for all endpoints

workspace/                    # Isolated project directories (workspace/<project-id>/)
```

---

## Data Models

All models share these conventions:
- Primary keys are UUID4 strings, generated server-side at creation time (`str(uuid.uuid4())`)
- Timestamps are `datetime` in UTC, stored as `DateTime(timezone=True)`
- No SQLite-only column types — `JSON` payload stored as `Text` via `sa.Text` with manual `json.dumps/loads`, ensuring PostgreSQL compatibility
- Cascade deletes from `Project` to all children

### `database.py` — SQLAlchemy engine and session factory

Plain SQLAlchemy 2.x is used rather than Flask-SQLAlchemy. The existing `pyproject.toml` already declares `sqlalchemy>=2.0,<3` — no new dependency is required.

The database module exposes:
- `Base`: the `DeclarativeBase` subclass all models inherit from
- `get_engine(database_url: str)`: creates and returns a `create_engine()` instance
- `get_session_factory(engine)`: returns a `sessionmaker` bound to the engine
- `get_db(app)`: returns the scoped session stored on `flask.g` for the current request, creating it on first call

Database session lifecycle in `create_app()`:
- `engine` and `session_factory` are created once at startup and stored on `app`
- Each request opens a session via `get_db()` on first use
- `teardown_appcontext` closes and removes the session after each request
- `Base.metadata.create_all(engine)` is called once at startup to initialise the schema

```python
# app/models/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase, scoped_session
import flask

class Base(DeclarativeBase):
    pass

def get_engine(database_url: str):
    return create_engine(database_url)

def get_session_factory(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)

def get_db() -> "Session":
    """Return the request-scoped SQLAlchemy session stored on flask.g."""
    if "db" not in flask.g:
        flask.g.db = flask.current_app.session_factory()
    return flask.g.db
```

**Design note:** All model classes inherit from `Base` (not `db.Model`). The `flask.g`-based session is passed explicitly to every service call, preserving the no-Flask-import rule for the service and agent layers.

### `Project`

```python
class Project(Base):
    __tablename__ = "projects"

    id:          str           # UUID4, PK
    title:       str           # non-nullable, max 255 chars
    description: str           # non-nullable, Text
    status:      str           # non-nullable, CHECK constraint (project lifecycle values)
    created_at:  datetime      # non-nullable, UTC
    updated_at:  datetime      # non-nullable, UTC

    # Relationships (cascade delete)
    tasks:        list[Task]          # one-to-many
    events:       list[Event]         # one-to-many
    messages:     list[Message]       # one-to-many
    dependencies: list[TaskDependency] # one-to-many (via project_id FK)
```

Valid `status` values: `draft`, `planning`, `in_progress`, `review`, `blocked`, `delivered`, `cancelled`

### `Task`

```python
class Task(Base):
    __tablename__ = "tasks"

    id:            str       # UUID4, PK
    project_id:    str       # FK → projects.id, non-nullable
    title:         str       # non-nullable, max 255 chars
    description:   str       # nullable, Text
    assigned_role: str       # non-nullable, CHECK constraint (AgentRole values)
    priority:      str       # non-nullable, CHECK constraint (low/medium/high)
    status:        str       # non-nullable, CHECK constraint (task lifecycle values)
    created_at:    datetime  # non-nullable, UTC
    updated_at:    datetime  # non-nullable, UTC

    # Relationships
    project:                Project
    prerequisite_edges:     list[TaskDependency]  # edges where this task is the dependent
    dependent_edges:        list[TaskDependency]  # edges where this task is the prerequisite
    events:                 list[Event]
    messages:               list[Message]
```

Valid `status` values: `backlog`, `ready`, `in_progress`, `review`, `blocked`, `rework`, `done`

### `TaskDependency`

```python
class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint("prerequisite_task_id", "dependent_task_id"),
    )

    id:                   str       # UUID4, PK
    project_id:           str       # FK → projects.id, non-nullable
    prerequisite_task_id: str       # FK → tasks.id, non-nullable
    dependent_task_id:    str       # FK → tasks.id, non-nullable
    created_at:           datetime  # non-nullable, UTC
```

The `foreign_keys` argument is required in the `relationship()` declarations on `Task` because two FK columns on `TaskDependency` both reference `tasks.id`. SQLAlchemy requires explicit disambiguation.

### `Event`

```python
class Event(Base):
    __tablename__ = "events"

    id:          str       # UUID4, PK
    project_id:  str       # FK → projects.id, non-nullable
    task_id:     str       # FK → tasks.id, nullable
    event_name:  str       # non-nullable, max 255 chars
    payload:     str       # non-nullable, Text — stores JSON string
    created_at:  datetime  # non-nullable, UTC

    # Helper properties
    @property
    def payload_dict(self) -> dict:
        return json.loads(self.payload)
```

Payload is stored as a JSON string in a `Text` column rather than a native `JSON` column, ensuring identical behavior between SQLite and PostgreSQL without dialect-specific handling.

### `Message`

```python
class Message(Base):
    __tablename__ = "messages"

    id:           str       # UUID4, PK
    project_id:   str       # FK → projects.id, non-nullable
    task_id:      str       # FK → tasks.id, nullable
    sender_role:  str       # non-nullable, max 100 chars
    message_type: str       # non-nullable, max 100 chars
    body:         str       # non-nullable, Text
    created_at:   datetime  # non-nullable, UTC
```

### Cascade Delete Strategy

```python
# In Project model:
tasks = relationship("Task", back_populates="project",
                     cascade="all, delete-orphan", passive_deletes=True)
events = relationship("Event", back_populates="project",
                      cascade="all, delete-orphan", passive_deletes=True)
messages = relationship("Message", back_populates="project",
                        cascade="all, delete-orphan", passive_deletes=True)
dependencies = relationship("TaskDependency", back_populates="project",
                             cascade="all, delete-orphan", passive_deletes=True)
```

---

## Enumerations and Constants

All enumerations live in `app/constants.py` and are imported throughout the application. Using `enum.Enum` rather than bare strings ensures typo-safety and enables IDE-level completion.

### `AgentRole`

```python
class AgentRole(str, Enum):
    manager   = "manager"
    designer  = "designer"
    frontend  = "frontend"
    backend   = "backend"
    qa        = "qa"
    utility   = "utility"
```

### `ProjectStatus`

```python
class ProjectStatus(str, Enum):
    draft       = "draft"
    planning    = "planning"
    in_progress = "in_progress"
    review      = "review"
    blocked     = "blocked"
    delivered   = "delivered"
    cancelled   = "cancelled"
```

### `TaskStatus`

```python
class TaskStatus(str, Enum):
    backlog     = "backlog"
    ready       = "ready"
    in_progress = "in_progress"
    review      = "review"
    blocked     = "blocked"
    rework      = "rework"
    done        = "done"
```

### `TaskPriority`

```python
class TaskPriority(str, Enum):
    low    = "low"
    medium = "medium"
    high   = "high"
```

### Permitted Task Status Transitions

```python
TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.backlog:     {TaskStatus.ready},
    TaskStatus.ready:       {TaskStatus.in_progress},
    TaskStatus.in_progress: {TaskStatus.review, TaskStatus.blocked},
    TaskStatus.review:      {TaskStatus.done, TaskStatus.rework},
    TaskStatus.blocked:     {TaskStatus.in_progress},
    TaskStatus.rework:      {TaskStatus.in_progress, TaskStatus.done},
    TaskStatus.done:        set(),  # terminal
}
```

### Permitted Project Status Transitions

```python
PROJECT_TRANSITIONS: dict[ProjectStatus, set[ProjectStatus]] = {
    ProjectStatus.draft:       {ProjectStatus.planning, ProjectStatus.cancelled},
    ProjectStatus.planning:    {ProjectStatus.in_progress, ProjectStatus.blocked, ProjectStatus.cancelled},
    ProjectStatus.in_progress: {ProjectStatus.review, ProjectStatus.blocked, ProjectStatus.cancelled},
    ProjectStatus.review:      {ProjectStatus.delivered, ProjectStatus.in_progress, ProjectStatus.blocked},
    ProjectStatus.blocked:     {ProjectStatus.in_progress, ProjectStatus.cancelled},
    ProjectStatus.delivered:   set(),  # terminal
    ProjectStatus.cancelled:   set(),  # terminal
}
```

### Event Name Constants

```python
class EventName:
    PROJECT_CREATED          = "project.created"
    PROJECT_STATUS_CHANGED   = "project.status_changed"
    MANAGER_PLANNING_STARTED = "manager.planning_started"
    MANAGER_PLANNING_COMPLETED = "manager.planning_completed"
    MANAGER_PLANNING_FAILED  = "manager.planning_failed"
    TASK_CREATED             = "task.created"
    TASK_STATUS_CHANGED      = "task.status_changed"
```

---

## Pydantic Schemas

### LLM Output: `ProjectPlan`

This is the structured output the Manager Agent asks the LLM to return. It is validated before any application logic acts on it.

```python
from pydantic import BaseModel, field_validator, model_validator
from app.constants import AgentRole, TaskPriority

class PlanTask(BaseModel):
    local_id:     str           # local reference key within this plan (e.g. "TASK-1")
    title:        str
    description:  str
    assigned_role: AgentRole    # validated against AgentRole enum
    priority:     TaskPriority  # validated against TaskPriority enum
    dependencies: list[str] = []  # list of local_id strings from this same plan

class ProjectPlan(BaseModel):
    tasks: list[PlanTask]

    @model_validator(mode="after")
    def validate_task_count(self) -> "ProjectPlan":
        if len(self.tasks) == 0:
            raise ValueError("ProjectPlan must contain at least one task")
        return self

    @model_validator(mode="after")
    def validate_dependency_references(self) -> "ProjectPlan":
        local_ids = {t.local_id for t in self.tasks}
        for task in self.tasks:
            for dep in task.dependencies:
                if dep not in local_ids:
                    raise ValueError(
                        f"Task '{task.local_id}' references unknown dependency '{dep}'"
                    )
        return self
```

**Design decision:** `AgentRole` and `TaskPriority` are `str, Enum` subclasses, so Pydantic v2 accepts their string representations directly. Invalid role strings fail Pydantic validation and cause `planning_failed` — there is no role-substitution fallback. This keeps LLM output validation strict and ensures the prompt is the single source of truth for valid role values.

### Agent Infrastructure

```python
class ModelConfig(BaseModel):
    provider: str   # e.g. "openai"
    model:    str   # e.g. "gpt-4o"

class AgentResult(BaseModel):
    status: Literal["success", "failure", "not_implemented"]
    output: dict
    error:  str | None = None
```

### API Request Schemas

```python
class CreateProjectRequest(BaseModel):
    title:       str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=5000)

class UpdateProjectStatusRequest(BaseModel):
    status: ProjectStatus  # validated against enum

class UpdateTaskStatusRequest(BaseModel):
    status: TaskStatus     # validated against enum
```

**Design decision:** The description field uses 5000 characters as the single canonical maximum across all layers — `CreateProjectRequest` Pydantic schema, the service layer, and the UI form. There is no separate route-level limit. All layers enforce the same 5000-character boundary.

### Response Serialization

Services return SQLAlchemy model instances. Routes call a `to_dict()` method on each model for serialization. This avoids a separate Pydantic response schema layer while keeping serialization logic close to the model.

```python
# Example on Project model
def to_dict(self) -> dict:
    return {
        "id":          self.id,
        "title":       self.title,
        "description": self.description,
        "status":      self.status,
        "created_at":  self.created_at.isoformat() + "Z",
        "updated_at":  self.updated_at.isoformat() + "Z",
    }
```

All timestamps are serialized as ISO 8601 UTC strings (`YYYY-MM-DDTHH:MM:SSZ`).

---

## Agent Abstraction

### `BaseAgent` (app/agents/base.py)

```python
from abc import ABC, abstractmethod
from app.constants import AgentRole
from app.schemas import ModelConfig, AgentResult

class BaseAgent(ABC):
    name:         str
    role:         AgentRole
    model_config: ModelConfig

    @abstractmethod
    def run(self, task: "Task", context: dict) -> AgentResult:
        """Execute the agent's work for a given task. Must return AgentResult."""
        ...
```

`BaseAgent` has no Flask imports, no SQLAlchemy imports, and no hard-coded provider names. Any database session needed is passed through `context` or the calling service.

### `ManagerAgent` (app/agents/manager.py)

The Manager Agent is invoked differently from specialist agents — it operates on a project, not a task. Its entry point is `plan()` rather than `run()`.

```python
class ManagerAgent(BaseAgent):
    name = "Manager"
    role = AgentRole.manager

    def __init__(self, llm_router: "LLMRouter", model_config: ModelConfig):
        self.llm_router   = llm_router
        self.model_config = model_config

    def plan(
        self,
        project_id: str,
        title:       str,
        description: str,
        task_service:  "TaskService",
        event_service: "EventService",
        session:       "Session",
    ) -> None:
        """
        Invokes the LLM, validates the response as ProjectPlan,
        persists tasks and dependencies, transitions project status.
        All DB writes delegated to services.
        """
        ...

    def _build_prompt(self, title: str, description: str) -> str:
        """Constructs the structured prompt for the LLM."""
        ...

    def run(self, task: "Task", context: dict) -> AgentResult:
        # Manager is not dispatched as a task-level agent in Phase 1.
        return AgentResult(
            status="not_implemented",
            output={},
            error="Manager.run() is not used in Phase 1; use plan() instead."
        )
```

**Prompt structure** (`_build_prompt` output):

```
You are the Manager Agent for AgentHQ.

Your job is to analyze a software project requirement and produce a structured task plan.

Project Title: {title}
Project Description: {description}

Return a JSON object with this exact structure:
{
  "tasks": [
    {
      "local_id": "TASK-1",
      "title": "...",
      "description": "...",
      "assigned_role": "<one of: manager|designer|frontend|backend|qa|utility>",
      "priority": "<one of: low|medium|high>",
      "dependencies": ["TASK-N", ...]  // local_ids of tasks this one depends on
    }
  ]
}

Rules:
- Return ONLY the JSON object. No explanation, no markdown code fences.
- Every task must have a unique local_id.
- dependencies must reference local_ids from within this same plan.
- assigned_role must be one of the listed values.
- priority must be one of the listed values.
```

**Manager planning flow in detail:**

```
plan() called
  │
  ├─ EventService.record(manager.planning_started)
  │
  ├─ raw = LLMRouter.complete(role="MANAGER", prompt=_build_prompt(...))
  │
  ├─ try: plan = ProjectPlan.model_validate_json(raw)
  │   except ValidationError:
  │       EventService.record(manager.planning_failed, {reason: <safe message>})
  │       ProjectService.update_status(blocked)
  │       return
  │
  ├─ persist tasks: TaskService.create_task() for each plan entry
  │   └─ build local_id → db_id mapping for dependency resolution
  │
  ├─ persist dependencies:
  │   for each task with deps:
  │       for each dep local_id:
  │           prereq_db_id = local_id_map.get(dep)
  │           if prereq_db_id is None:
  │               record warning in planning_completed payload (skip)
  │           else:
  │               TaskService.create_task_dependency(prerequisite=prereq_db_id, dependent=task_db_id)
  │
  ├─ ProjectService.update_status(in_progress)
  │
  └─ EventService.record(manager.planning_completed, {task_count: N, ...})
```

### Stub Agents — Phase 1 Role Definitions Only

The five non-manager roles exist in Phase 1 purely as role definitions and interface placeholders. They do NOT perform any LLM calls and do NOT require provider or model configuration. Their sole purpose is to make the `AgentRole` registry complete so Phase 2 can replace each stub with a real implementation without altering any other module.

Each stub in `designer.py`, `frontend.py`, `backend.py`, `qa.py`, `utility.py` follows this pattern:

```python
class DesignerAgent(BaseAgent):
    name = "Designer"
    role = AgentRole.designer

    # No model_config or llm_router — stubs do not invoke LLMs
    def __init__(self) -> None:
        self.model_config = ModelConfig(provider="stub", model="stub")

    def run(self, task: "Task", context: dict) -> AgentResult:
        return AgentResult(
            status="not_implemented",
            output={},
            error="Agent designer is not yet implemented",
        )
```

**Phase 2 contract:** When a specialist agent is implemented, its constructor is updated to accept an `LLMRouter` reference and a real `ModelConfig`. The `AGENT_REGISTRY` entry and all call sites remain unchanged.

### Agent Registry

```python
# app/agents/__init__.py
AGENT_REGISTRY: dict[AgentRole, BaseAgent] = {}

def build_registry(llm_router: "LLMRouter", app_config: "AppConfig") -> None:
    """
    Called from create_app() after config is loaded.
    Only ManagerAgent receives real LLM infrastructure.
    All other roles are registered as stubs with no LLM dependency.
    """
    AGENT_REGISTRY[AgentRole.manager]  = ManagerAgent(llm_router, app_config.manager_model_config)
    AGENT_REGISTRY[AgentRole.designer] = DesignerAgent()
    AGENT_REGISTRY[AgentRole.frontend] = FrontendAgent()
    AGENT_REGISTRY[AgentRole.backend]  = BackendAgent()
    AGENT_REGISTRY[AgentRole.qa]       = QAAgent()
    AGENT_REGISTRY[AgentRole.utility]  = UtilityAgent()
```

---

## LLM Provider Abstraction

### `BaseLLMProvider` (app/llm/base.py)

All providers implement a single interface. No provider-specific SDK is imported into business logic.

```python
from abc import ABC, abstractmethod

class BaseLLMProvider(ABC):
    @abstractmethod
    def complete(self, prompt: str, model: str, **kwargs) -> str:
        """
        Send prompt to the provider and return the raw response string.
        Raises LLMProviderError on any provider-side failure.
        """
        ...
```

### Provider Implementations

All three concrete providers use `httpx` for HTTP calls. `httpx` is a widely-used, synchronous-and-async capable HTTP client that is already available in the Python ecosystem. Adding it as a dependency (`httpx>=0.27,<1`) keeps all three providers on equal footing with no provider-specific SDK required.

**Dependency addition to `pyproject.toml`:**
```toml
"httpx>=0.27,<1",
```

#### `OpenAIProvider` (app/llm/providers/openai_provider.py)

Calls the OpenAI Chat Completions API (`POST https://api.openai.com/v1/chat/completions`).

```python
import os
import httpx
from app.llm.base import BaseLLMProvider
from app.exceptions import LLMProviderError

class OpenAIProvider(BaseLLMProvider):
    API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self) -> None:
        self._api_key = os.environ.get("OPENAI_API_KEY", "")
        # Key presence is validated lazily — error only fires when a call is made

    def complete(self, prompt: str, model: str, **kwargs) -> str:
        if not self._api_key:
            raise LLMProviderError("openai", "missing_api_key", "OPENAI_API_KEY is not set")
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
        try:
            resp = httpx.post(self.API_URL, headers=headers, json=body, timeout=60)
        except httpx.TransportError as exc:
            raise LLMProviderError("openai", "network_error", "Network error calling OpenAI") from exc
        if resp.status_code == 401:
            raise LLMProviderError("openai", "auth_failure", "OpenAI authentication failed")
        if resp.status_code == 429:
            raise LLMProviderError("openai", "rate_limit", "OpenAI rate limit exceeded")
        if not resp.is_success:
            raise LLMProviderError("openai", "api_error", f"OpenAI returned HTTP {resp.status_code}")
        return resp.json()["choices"][0]["message"]["content"] or ""
```

#### `AnthropicProvider` (app/llm/providers/anthropic_provider.py)

Calls the Anthropic Messages API (`POST https://api.anthropic.com/v1/messages`).

```python
import os
import httpx
from app.llm.base import BaseLLMProvider
from app.exceptions import LLMProviderError

class AnthropicProvider(BaseLLMProvider):
    API_URL      = "https://api.anthropic.com/v1/messages"
    API_VERSION  = "2023-06-01"

    def __init__(self) -> None:
        self._api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    def complete(self, prompt: str, model: str, **kwargs) -> str:
        if not self._api_key:
            raise LLMProviderError("anthropic", "missing_api_key", "ANTHROPIC_API_KEY is not set")
        headers = {
            "x-api-key":         self._api_key,
            "anthropic-version": self.API_VERSION,
            "Content-Type":      "application/json",
        }
        body = {
            "model":      model,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "messages":   [{"role": "user", "content": prompt}],
        }
        try:
            resp = httpx.post(self.API_URL, headers=headers, json=body, timeout=60)
        except httpx.TransportError as exc:
            raise LLMProviderError("anthropic", "network_error", "Network error calling Anthropic") from exc
        if resp.status_code == 401:
            raise LLMProviderError("anthropic", "auth_failure", "Anthropic authentication failed")
        if resp.status_code == 429:
            raise LLMProviderError("anthropic", "rate_limit", "Anthropic rate limit exceeded")
        if not resp.is_success:
            raise LLMProviderError("anthropic", "api_error", f"Anthropic returned HTTP {resp.status_code}")
        return resp.json()["content"][0]["text"] or ""
```

#### `GeminiProvider` (app/llm/providers/gemini_provider.py)

Calls the Google Gemini `generateContent` API (`POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`).

```python
import os
import httpx
from app.llm.base import BaseLLMProvider
from app.exceptions import LLMProviderError

class GeminiProvider(BaseLLMProvider):
    API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self) -> None:
        self._api_key = os.environ.get("GEMINI_API_KEY", "")

    def complete(self, prompt: str, model: str, **kwargs) -> str:
        if not self._api_key:
            raise LLMProviderError("gemini", "missing_api_key", "GEMINI_API_KEY is not set")
        url  = f"{self.API_BASE}/{model}:generateContent?key={self._api_key}"
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            resp = httpx.post(url, json=body, timeout=60)
        except httpx.TransportError as exc:
            raise LLMProviderError("gemini", "network_error", "Network error calling Gemini") from exc
        if resp.status_code == 401:
            raise LLMProviderError("gemini", "auth_failure", "Gemini authentication failed")
        if resp.status_code == 429:
            raise LLMProviderError("gemini", "rate_limit", "Gemini rate limit exceeded")
        if not resp.is_success:
            raise LLMProviderError("gemini", "api_error", f"Gemini returned HTTP {resp.status_code}")
        candidates = resp.json().get("candidates", [])
        if not candidates:
            raise LLMProviderError("gemini", "empty_response", "Gemini returned no candidates")
        return candidates[0]["content"]["parts"][0]["text"] or ""
```

#### `OpenAICompatibleProvider` (app/llm/providers/openai_compatible_provider.py)

A general-purpose provider for any endpoint that implements the OpenAI Chat Completions wire format. Supports local models (Ollama, LM Studio), Azure OpenAI endpoints, and other OpenAI-compatible APIs without requiring separate provider implementations for each.

Unlike the named providers, `OpenAICompatibleProvider` is instantiated with explicit constructor arguments rather than reading fixed env var names. `build_provider_registry()` is responsible for extracting configuration values and constructing instances.

```python
import httpx
from app.llm.base import BaseLLMProvider
from app.exceptions import LLMProviderError

class OpenAICompatibleProvider(BaseLLMProvider):
    """
    Provider for any endpoint implementing the OpenAI Chat Completions API.

    Args:
        base_url:      Full URL to the completions endpoint,
                       e.g. "http://localhost:11434/v1/chat/completions" for Ollama.
        api_key:       Bearer token; pass an empty string for unauthenticated endpoints.
        provider_name: Human-readable name used in error messages (e.g. "ollama").
    """

    def __init__(self, base_url: str, api_key: str, provider_name: str = "openai_compatible") -> None:
        self._base_url      = base_url
        self._api_key       = api_key
        self._provider_name = provider_name

    def complete(self, prompt: str, model: str, **kwargs) -> str:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
        try:
            resp = httpx.post(self._base_url, headers=headers, json=body, timeout=60)
        except httpx.TransportError as exc:
            raise LLMProviderError(
                self._provider_name, "network_error",
                f"Network error calling {self._provider_name}"
            ) from exc
        if resp.status_code == 401:
            raise LLMProviderError(self._provider_name, "auth_failure",
                                   f"{self._provider_name} authentication failed")
        if resp.status_code == 429:
            raise LLMProviderError(self._provider_name, "rate_limit",
                                   f"{self._provider_name} rate limit exceeded")
        if not resp.is_success:
            raise LLMProviderError(self._provider_name, "api_error",
                                   f"{self._provider_name} returned HTTP {resp.status_code}")
        return resp.json()["choices"][0]["message"]["content"] or ""
```

**Usage:** To route the Manager Agent to a local Ollama instance, set:
```dotenv
OAICOMPAT_OLLAMA_BASE_URL=http://localhost:11434/v1/chat/completions
AGENT_MANAGER_PROVIDER=ollama
```
No changes to agent business logic or the LLMRouter are required.

### `LLMRouter` (app/llm/router.py)

The router is unchanged from the original design. It accepts a `role_configs` dict and `provider_registry` dict at construction, resolves the correct provider at call time, and never contains provider-specific logic.

```python
class LLMRouter:
    def __init__(
        self,
        role_configs: dict[str, tuple[str, str]],  # role → (provider_name, model)
        provider_registry: dict[str, BaseLLMProvider],
    ) -> None:
        self._role_configs      = role_configs
        self._provider_registry = provider_registry

    def complete(self, role: str, prompt: str, **kwargs) -> str:
        # 1. Validate role format
        if not re.match(r"^[A-Z_]{1,64}$", role):
            raise ValueError(f"Invalid role identifier: '{role}'")

        # 2. Validate role is configured
        if role not in self._role_configs:
            raise ConfigurationError(variable_name=f"AGENT_{role}_MODEL")

        # 3. Validate prompt length
        if not prompt or len(prompt) > 32768:
            raise ValueError(f"Prompt length {len(prompt)} is not in range [1, 32768]")

        # 4. Resolve provider
        provider_name, model = self._role_configs[role]
        provider = self._provider_registry.get(provider_name)
        if provider is None:
            raise ConfigurationError(variable_name=f"AGENT_{role}_PROVIDER")

        # 5. Delegate — NO logging of prompt or response
        return provider.complete(prompt=prompt, model=model, **kwargs)
```

**Adding a new provider** requires only: (1) create a new file implementing `BaseLLMProvider`; (2) register it in `build_provider_registry()`; (3) set `AGENT_<ROLE>_PROVIDER=<name>` in `.env`. No agent or service code changes.

### Provider Registry (app/llm/providers/__init__.py)

```python
import os
from app.llm.providers.openai_provider             import OpenAIProvider
from app.llm.providers.anthropic_provider          import AnthropicProvider
from app.llm.providers.gemini_provider             import GeminiProvider
from app.llm.providers.openai_compatible_provider  import OpenAICompatibleProvider
from app.llm.base import BaseLLMProvider

def build_provider_registry() -> dict[str, BaseLLMProvider]:
    """
    Instantiates all known providers at startup.

    Named providers (openai, anthropic, gemini) are always registered; missing
    API keys surface lazily when a request is actually routed to that provider.

    OpenAI-compatible providers are registered dynamically: any env var matching
    OAICOMPAT_<NAME>_BASE_URL causes a provider named <name> to be registered.
    Example: OAICOMPAT_OLLAMA_BASE_URL=http://localhost:11434/v1/chat/completions
    registers a provider under the key "ollama".
    """
    registry: dict[str, BaseLLMProvider] = {
        "openai":    OpenAIProvider(),
        "anthropic": AnthropicProvider(),
        "gemini":    GeminiProvider(),
    }

    # Register any OpenAI-compatible endpoints declared via env vars.
    # Convention: OAICOMPAT_<NAME>_BASE_URL and optional OAICOMPAT_<NAME>_API_KEY.
    for key, value in os.environ.items():
        if key.startswith("OAICOMPAT_") and key.endswith("_BASE_URL") and value:
            name = key[len("OAICOMPAT_"):-len("_BASE_URL")].lower()
            api_key = os.environ.get(f"OAICOMPAT_{name.upper()}_API_KEY", "")
            registry[name] = OpenAICompatibleProvider(
                base_url=value,
                api_key=api_key,
                provider_name=name,
            )

    return registry
```

**Design rationale:** Named providers (`openai`, `anthropic`, `gemini`) are always registered at startup regardless of which API keys are present — missing keys surface lazily at request time. `OpenAICompatibleProvider` instances are registered dynamically based on `OAICOMPAT_<NAME>_BASE_URL` environment variables, so Phase 2 agents can point at local models or Azure without any code changes. A developer configuring only `ANTHROPIC_API_KEY` can use Anthropic for the Manager role without needing OpenAI or Gemini keys.

### Exception Classes (app/exceptions.py)

```python
class ConfigurationError(RuntimeError):
    def __init__(self, variable_name: str):
        self.variable_name = variable_name
        super().__init__(f"Missing or invalid configuration variable: {variable_name}")

class LLMProviderError(RuntimeError):
    def __init__(self, provider: str, category: str, message: str):
        self.provider = provider
        self.category = category
        super().__init__(message)

class InvalidTransitionError(ValueError):
    def __init__(self, task_id: str, current: str, target: str):
        self.task_id = task_id
        self.current = current
        self.target  = target
        super().__init__(
            f"Transition from '{current}' to '{target}' is not allowed for task '{task_id}'"
        )

class WorkspaceBoundaryError(PermissionError):
    def __init__(self, attempted_path: str, workspace_root: str):
        self.attempted_path = attempted_path
        self.workspace_root = workspace_root
        super().__init__(
            f"Path '{attempted_path}' is outside workspace root '{workspace_root}'"
        )

class NotFoundError(LookupError):
    def __init__(self, resource: str, resource_id: str):
        self.resource    = resource
        self.resource_id = resource_id
        super().__init__(f"{resource} '{resource_id}' not found")
```

---

## Service Layer

Services are pure Python — no Flask imports, no direct HTTP concepts. They receive a SQLAlchemy `Session` as a parameter and raise domain exceptions that routes translate to HTTP responses.

### `ProjectService` (app/services/project_service.py)

```python
def create_project(session: Session, title: str, description: str) -> Project:
    """
    Validates input, creates Project (status=draft), records project.created event.
    Raises: ValueError on invalid input.
    """

def get_project(session: Session, project_id: str) -> Project:
    """
    Returns Project by id.
    Raises: NotFoundError if not found.
    """

def list_projects(session: Session) -> list[Project]:
    """Returns all projects ordered by created_at descending."""

def update_project_status(
    session: Session, project_id: str, new_status: ProjectStatus
) -> Project:
    """
    Validates transition against PROJECT_TRANSITIONS.
    Updates status, records project.status_changed event.
    Raises: NotFoundError, InvalidTransitionError.
    """

def trigger_planning(
    session:       Session,
    project_id:    str,
    manager_agent: "ManagerAgent",
    task_service:  "TaskService",
    event_service: "EventService",
) -> None:
    """
    Owns the complete atomic planning transaction:
      1. Validates project exists and status permits planning (raises NotFoundError,
         InvalidTransitionError, or ConflictError if not).
      2. Transitions project to `planning` and records `manager.planning_started`.
      3. Calls manager_agent.plan(), which persists tasks, dependencies, and events.
      4. Commits on success.
      5. On any exception after step 2, rolls back the session to its pre-call state
         and re-raises so the route layer can return the appropriate HTTP response.

    The route layer MUST NOT wrap this call in its own rollback logic.
    Raises: NotFoundError, InvalidTransitionError, ConflictError, LLMProviderError,
            RuntimeError (propagated from EventService on DB write failure).
    """
```

### `TaskService` (app/services/task_service.py)

```python
def create_task(
    session:       Session,
    project_id:    str,
    title:         str,
    description:   str,
    assigned_role: AgentRole,
    priority:      TaskPriority,
) -> Task:
    """
    Creates task with status=backlog.
    If no prerequisites exist, immediately transitions to ready.
    Records task.created event.
    """

def get_task(session: Session, project_id: str, task_id: str) -> Task:
    """Returns Task, validating it belongs to project_id. Raises NotFoundError."""

def list_tasks(session: Session, project_id: str) -> list[Task]:
    """Returns all tasks for a project."""

def update_task_status(
    session:    Session,
    project_id: str,
    task_id:    str,
    new_status: TaskStatus,
) -> Task:
    """
    Validates transition. Updates status. Records task.status_changed event.
    If new_status == done: calls evaluate_dependents().
    All operations in a single transaction — rolled back on any failure.
    Raises: NotFoundError, InvalidTransitionError.
    """

def evaluate_dependents(
    session:            Session,
    project_id:         str,
    completed_task_id:  str,
) -> list[Task]:
    """
    Queries all TaskDependency records where prerequisite_task_id == completed_task_id.
    For each dependent: checks if ALL its prerequisites are done.
    Promotes qualifying dependents to ready and records task.status_changed events.
    Returns list of promoted tasks.
    """

def create_task_dependency(
    session:          Session,
    project_id:       str,
    prerequisite_id:  str,
    dependent_id:     str,
) -> TaskDependency:
    """
    Validates both tasks exist in project.
    Rejects self-dependency.
    Runs DFS cycle detection.
    Persists TaskDependency.
    Raises: NotFoundError, ValueError (self-dep or cycle), IntegrityError (duplicate).
    """

def get_task_dependencies(
    session:    Session,
    project_id: str,
    task_id:    str,
) -> dict:
    """
    Returns:
    {
        "prerequisites": [task.to_dict(), ...],  # tasks this task depends on
        "dependents":    [task.to_dict(), ...],  # tasks that depend on this task
    }
    """
```

### `EventService` (app/services/event_service.py)

```python
def record(
    session:    Session,
    project_id: str,
    event_name: str,
    payload:    dict,
    task_id:    str | None = None,
) -> Event:
    """
    Redacts secret keys in payload, serializes to JSON, persists Event.
    Raises: RuntimeError if DB write fails.
    """

def list_events(session: Session, project_id: str) -> list[Event]:
    """Returns all events for a project ordered by created_at ascending."""

def _redact_secrets(payload: dict) -> dict:
    """
    Replaces values of keys matching the secret pattern with "[REDACTED]".
    Applied to top-level keys only. Non-destructive (returns new dict).
    """
```

---

## Flask Routes / API Endpoints

### Shared Conventions

- All API endpoints return `Content-Type: application/json`
- `project_id` and `task_id` path params are validated as UUID4 before calling any service
- Pydantic request validation failures return `422 {"error": "...", "code": "validation_error", "fields": {...}}`
- `NotFoundError` → `404 {"error": "...", "code": "not_found"}`
- `InvalidTransitionError` → `422 {"error": "...", "code": "invalid_transition"}`
- `ConflictError` → `409 {"error": "...", "code": "conflict"}`
- Unhandled exceptions → `500 {"error": "An internal error occurred.", "code": "internal_error"}`

### API Blueprint (`app/routes/api.py`, prefix `/api`)

---

**`POST /api/projects`**
- Request: `CreateProjectRequest` (title, description)
- Services: `ProjectService.create_project()`
- Success: `201 {"project": project.to_dict()}`
- Errors: `422` (validation), `500` (db error)

---

**`GET /api/projects`**
- Request: none
- Services: `ProjectService.list_projects()`
- Success: `200 {"projects": [project.to_dict(), ...]}`

---

**`GET /api/projects/<project_id>`**
- Services: `ProjectService.get_project()`
- Success: `200 {"project": project.to_dict()}`
- Errors: `400` (invalid UUID), `404`

---

**`PATCH /api/projects/<project_id>/status`**
- Request: `UpdateProjectStatusRequest` (status)
- Services: `ProjectService.update_project_status()`
- Success: `200 {"project": project.to_dict()}`
- Errors: `400`, `404`, `422` (invalid transition or status value)

---

**`GET /api/projects/<project_id>/tasks`**
- Services: `TaskService.list_tasks()`
- Success: `200 {"tasks": [task.to_dict(), ...]}`
- Errors: `400`, `404`

---

**`GET /api/projects/<project_id>/tasks/<task_id>`**
- Services: `TaskService.get_task()`
- Success: `200 {"task": task.to_dict()}`  — includes `prerequisite_ids` and `dependent_ids` arrays
- Errors: `400`, `404`

---

**`PATCH /api/projects/<project_id>/tasks/<task_id>/status`**
- Request: `UpdateTaskStatusRequest` (status)
- Services: `TaskService.update_task_status()`
- Success: `200 {"task": task.to_dict()}`
- Errors: `400`, `404`, `422`

---

**`GET /api/projects/<project_id>/tasks/<task_id>/dependencies`**
- Services: `TaskService.get_task_dependencies()`
- Success: `200 {"prerequisites": [...], "dependents": [...]}`
- Errors: `400`, `404`

---

**`GET /api/projects/<project_id>/events`**
- Services: `EventService.list_events()`
- Success: `200 {"events": [event.to_dict(), ...]}`
- Errors: `400`, `404`

---

**`POST /api/projects/<project_id>/plan`**
- Request: none (project_id is sufficient)
- Services: `ProjectService.trigger_planning()`; internally invokes `ManagerAgent.plan()`
- Success: `200 {"status": "planning_triggered"}`
- Errors: `400`, `404`, `409` (already planning/in_progress), `500`

---

### UI Blueprint (`app/routes/ui.py`, no prefix)

**`GET /`** → `dashboard.html` with all projects (summary list, status badge, timestamp)

**`GET /projects/new`** → `project_form.html` with empty form

**`GET /projects/<project_id>`** → `project_detail.html` with project, task list, activity feed; renders explicit empty state when no tasks or events exist

All UI routes render an error page (not JSON) for 404/500.

---

## Application Factory

### `app/config.py`

```python
import os
from app.constants import AgentRole
from app.schemas import ModelConfig
from app.exceptions import ConfigurationError

# Only the Manager Agent requires real LLM configuration at startup.
# Stub agents (designer, frontend, backend, qa, utility) do not invoke LLMs in Phase 1
# and therefore do not require real provider/model env vars.
REQUIRED_VARS = [
    "SECRET_KEY",
    "AGENT_MANAGER_MODEL",
    "AGENT_MANAGER_PROVIDER",
]

# Roles whose config is loaded from env if present, defaulting to "stub" if absent.
# This allows the LLMRouter registry to include all roles without requiring
# every role to have a configured provider in Phase 1.
STUB_ROLES = [
    AgentRole.designer,
    AgentRole.frontend,
    AgentRole.backend,
    AgentRole.qa,
    AgentRole.utility,
]

class AppConfig:
    secret_key:           str
    database_url:         str
    manager_model_config: ModelConfig

    # Role → (provider_name, model) for LLMRouter
    llm_role_configs: dict[str, tuple[str, str]]

    def __init__(self, overrides: dict | None = None) -> None:
        """
        Load configuration from environment variables, with `overrides` taking
        precedence over os.environ for every key lookup.  This allows tests to
        supply required values through create_app(config=...) without having to
        set real environment variables.  Production callers pass no overrides.
        """
        # Merge: overrides win, then fall back to os.environ
        self._env: dict[str, str] = {**os.environ, **(overrides or {})}

        for var in REQUIRED_VARS:
            if not self._env.get(var):
                raise ConfigurationError(variable_name=var)

        self.secret_key   = self._env["SECRET_KEY"]
        self.database_url = self._env.get("DATABASE_URL", "sqlite:///agenthq.db")
        self._load_model_configs()

    def _load_model_configs(self) -> None:
        self.llm_role_configs = {}

        # Manager: required
        manager_model    = self._env["AGENT_MANAGER_MODEL"]
        manager_provider = self._env["AGENT_MANAGER_PROVIDER"]
        self.llm_role_configs["MANAGER"] = (manager_provider, manager_model)
        self.manager_model_config = ModelConfig(provider=manager_provider, model=manager_model)

        # Stub roles: load from env/overrides if present, otherwise default to "stub"/"stub"
        for role in STUB_ROLES:
            role_upper = role.value.upper()
            model    = self._env.get(f"AGENT_{role_upper}_MODEL",    "stub")
            provider = self._env.get(f"AGENT_{role_upper}_PROVIDER", "stub")
            self.llm_role_configs[role_upper] = (provider, model)
```

### `app/__init__.py`

```python
from flask import Flask, g
from dotenv import load_dotenv
from app.config import AppConfig
from app.models.database import Base, get_engine, get_session_factory, get_db
from app.routes.api import api_bp
from app.routes.ui import ui_bp
from app.llm.providers import build_provider_registry
from app.llm.router import LLMRouter
from app.agents import build_registry

def create_app(config: dict | None = None) -> Flask:
    load_dotenv()

    # Pass config overrides to AppConfig BEFORE validation so that test-supplied
    # values for SECRET_KEY, DATABASE_URL, AGENT_MANAGER_MODEL, etc. are visible
    # during the required-variable check.  Production callers pass config=None.
    app_config = AppConfig(overrides=config)

    app = Flask(__name__)
    app.config["SECRET_KEY"]   = app_config.secret_key
    app.config["DATABASE_URL"] = app_config.database_url

    # Apply any remaining Flask-level overrides (e.g. TESTING=True)
    if config:
        app.config.update(config)

    # Plain SQLAlchemy — no Flask-SQLAlchemy extension
    engine = get_engine(app.config["DATABASE_URL"])
    app.session_factory = get_session_factory(engine)
    Base.metadata.create_all(engine)

    @app.teardown_appcontext
    def close_db(exc=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    # Build LLM infrastructure
    provider_registry = build_provider_registry()
    llm_router = LLMRouter(
        role_configs=app_config.llm_role_configs,
        provider_registry=provider_registry,
    )

    # Build agent registry
    build_registry(llm_router, app_config)

    # Register blueprints
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(ui_bp)

    # Register error handlers
    _register_error_handlers(app)

    return app
```

### Blueprint Registration Order

1. `api_bp` (prefix `/api`)
2. `ui_bp` (no prefix)

API blueprint is registered first to ensure `/api` routes take precedence over any potential UI route conflicts.

---

## Cycle Detection Algorithm

Used in `TaskService.create_task_dependency()` before persisting a new edge.

**Problem:** Given a directed acyclic graph (DAG) of task dependencies, determine whether adding a new directed edge `u → v` (u = prerequisite, v = dependent) would create a cycle.

**Algorithm:** Standard DFS reachability check from the proposed dependent back to the proposed prerequisite.

**Intuition:** Adding `u → v` creates a cycle if and only if `v` can already reach `u` through the existing edges. We perform a DFS starting at `v` to check if `u` is reachable.

```python
def _would_create_cycle(
    session:          Session,
    project_id:       str,
    prerequisite_id:  str,  # u
    dependent_id:     str,  # v
) -> tuple[bool, list[str]]:
    """
    Returns (True, cycle_path) if adding u→v creates a cycle, else (False, []).
    cycle_path is the list of task_ids forming the cycle for the error message.
    """
    # Build in-memory adjacency list from existing edges in this project
    rows = session.query(TaskDependency).filter_by(project_id=project_id).all()
    # adjacency: prerequisite → set of dependents
    adj: dict[str, set[str]] = {}
    for row in rows:
        adj.setdefault(row.prerequisite_task_id, set()).add(row.dependent_task_id)

    # DFS from dependent_id to see if we can reach prerequisite_id
    visited: set[str]  = set()
    path:    list[str] = []

    def dfs(node: str) -> bool:
        if node == prerequisite_id:
            return True  # cycle found
        if node in visited:
            return False
        visited.add(node)
        path.append(node)
        for neighbor in adj.get(node, set()):
            if dfs(neighbor):
                return True
        path.pop()
        return False

    if dfs(dependent_id):
        cycle_path = path + [prerequisite_id]
        return True, cycle_path
    return False, []
```

**Complexity:** O(V + E) per call where V = tasks in the project, E = dependency edges in the project. Acceptable for Phase 1 scale.

**Edge cases handled:**
- Self-dependency (`u == v`) is rejected before this function is called
- Duplicate edges: the `UniqueConstraint` on `TaskDependency` catches this at DB level; the service checks before calling `_would_create_cycle`

---

## Event Payload Redaction

Applied in `EventService._redact_secrets()` before any payload is serialized to the database.

```python
import re

_SECRET_PATTERN = re.compile(r"(?i)(key|token|secret|password)")
_MAX_REDACT_DEPTH = 3

def _redact_secrets(payload: dict, _depth: int = 1) -> dict:
    """
    Returns a new dict with values replaced by "[REDACTED]" for any key whose
    name matches the secret pattern, applied recursively through depth 3.

    At depth > _MAX_REDACT_DEPTH the dict is returned as-is (no further descent),
    consistent with the requirement that payload must not store nested objects
    deeper than three levels.

    Non-destructive: returns a new dict; the original is not modified.
    """
    if _depth > _MAX_REDACT_DEPTH:
        return payload
    result = {}
    for k, v in payload.items():
        if _SECRET_PATTERN.search(k):
            result[k] = "[REDACTED]"
        elif isinstance(v, dict) and _depth < _MAX_REDACT_DEPTH:
            result[k] = _redact_secrets(v, _depth + 1)
        else:
            result[k] = v
    return result
```

**Pattern explained:**
- `(?i)` — case-insensitive
- `(key|token|secret|password)` — matches any key name containing these substrings
- Applied recursively through nested dicts up to depth 3; dicts beyond depth 3 are stored as-is per Requirement 8.1
- Only the value is replaced; the key name is preserved in storage (so the field is discoverable but its value is not)
- Non-dict values that do not match the secret pattern are passed through unchanged

---

## UI Templates Structure

### Base Layout (`templates/base.html`)

Provides:
- `<head>` with charset, viewport, CSS link
- Navigation bar with links to Dashboard (`/`), New Project (`/projects/new`)
- `{% block title %}` for page-specific title
- `{% block content %}` for page body
- JS script tag at bottom

### `templates/dashboard.html`

Extends `base.html`. Displays:
- Heading: "Projects"
- Button/link: "New Project"
- Table or card list of all projects: title, status badge (color-coded by status), creation timestamp
- Explicit empty state: "No projects yet. Create your first project." when the list is empty

### `templates/project_form.html`

Extends `base.html`. Displays:
- Form with fields: title (text input), description (textarea)
- Submit button: "Create Project"
- Vanilla JS: intercepts submit, `fetch("POST /api/projects", body=JSON)`, on success redirects to `/projects/<id>`, on failure displays inline error message

### `templates/project_detail.html`

Extends `base.html`. Displays:
- Project header: title, status badge, description, creation timestamp
- Task List section:
  - For each task: title, assigned_role badge, priority badge, status badge, dependency count
  - Inline status PATCH button per task (JS)
  - Explicit empty state: "No tasks yet. Trigger planning to create tasks." when task list is empty
- Activity Feed section:
  - Events in chronological order (oldest first)
  - Each event: human-readable label derived from `event_name`, timestamp, safe payload summary
  - Safe payload: renders top-level primitive values only; omits any key matching the redaction pattern
  - Explicit empty state: "No activity yet." when event list is empty

### Activity Feed Event Labels

```
"project.created"             → "Project created"
"project.status_changed"      → "Project status changed to {new_status}"
"manager.planning_started"    → "Manager started planning"
"manager.planning_completed"  → "Manager completed planning ({task_count} tasks created)"
"manager.planning_failed"     → "Planning failed: {reason}"
"task.created"                → "Task created: {title}"
"task.status_changed"         → "Task '{task_id}' status changed to {new_status}"
```

Labels are derived by a Jinja2 template filter or a helper function — not hard-coded per event in the template.

### Vanilla JS

`static/js/main.js` handles:
- Project creation form: `fetch` POST, redirect on success, inline error display on failure
- Task status update buttons: `fetch` PATCH, partial page refresh of the task row or full reload

No JavaScript framework. No bundler. No transpilation.

---

## Error Handling Strategy

### Global Error Handlers (`app/__init__.py`)

```python
def _register_error_handlers(app: Flask) -> None:

    @app.errorhandler(400)
    def bad_request(e):
        if request.path.startswith("/api"):
            return jsonify({"error": str(e), "code": "bad_request"}), 400
        return render_template("error.html", code=400, message="Bad request"), 400

    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith("/api"):
            return jsonify({"error": str(e), "code": "not_found"}), 404
        return render_template("error.html", code=404, message="Page not found"), 404

    @app.errorhandler(422)
    def unprocessable(e):
        # Pydantic validation errors arrive here via abort(422)
        return jsonify({"error": str(e), "code": "validation_error"}), 422

    @app.errorhandler(500)
    def internal_error(e):
        if request.path.startswith("/api"):
            return jsonify({"error": "An internal error occurred.", "code": "internal_error"}), 500
        return render_template("error.html", code=500, message="Internal error"), 500
```

### Route-Level Exception Handling

Routes catch domain exceptions and translate them:

```python
try:
    project = project_service.get_project(session, project_id)
except NotFoundError as e:
    return jsonify({"error": str(e), "code": "not_found"}), 404
except InvalidTransitionError as e:
    return jsonify({
        "error": str(e),
        "code": "invalid_transition",
        "current_status": e.current,
        "target_status":  e.target,
    }), 422
```

**Principles:**
- Stack traces never appear in any response
- Safe error messages are 200 characters maximum
- The `error` field is always a human-readable string; `code` is a machine-readable slug
- `WorkspaceBoundaryError` → `403 {"error": "Path access denied.", "code": "boundary_violation"}`
- `ConfigurationError` → logged at startup, not returned as HTTP response (fatal)

---

## Configuration and Secrets

### `.env.example`

```dotenv
# Flask
SECRET_KEY=change-me-in-production

# Database (defaults to sqlite:///agenthq.db if not set)
DATABASE_URL=sqlite:///agenthq.db

# LLM Provider Credentials — set the key(s) for the provider(s) you intend to use.
# Only the provider referenced by AGENT_MANAGER_PROVIDER needs a valid key in Phase 1.
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...

# Manager Agent — required. Choose one provider and the appropriate model name.
# OpenAI example:
AGENT_MANAGER_PROVIDER=openai
AGENT_MANAGER_MODEL=gpt-4o

# Anthropic example (uncomment to use instead):
# AGENT_MANAGER_PROVIDER=anthropic
# AGENT_MANAGER_MODEL=claude-3-5-sonnet-20241022

# Google Gemini example (uncomment to use instead):
# AGENT_MANAGER_PROVIDER=gemini
# AGENT_MANAGER_MODEL=gemini-1.5-pro

# Specialist Agent stubs (Phase 1 — no LLM calls; these values are informational only).
# In Phase 2, replace "stub" with a real provider and model when each agent is implemented.
AGENT_DESIGNER_PROVIDER=stub
AGENT_DESIGNER_MODEL=stub
AGENT_FRONTEND_PROVIDER=stub
AGENT_FRONTEND_MODEL=stub
AGENT_BACKEND_PROVIDER=stub
AGENT_BACKEND_MODEL=stub
AGENT_QA_PROVIDER=stub
AGENT_QA_MODEL=stub
AGENT_UTILITY_PROVIDER=stub
AGENT_UTILITY_MODEL=stub

# OpenAI-Compatible Providers (optional — for local models, Azure, etc.)
# Convention: OAICOMPAT_<NAME>_BASE_URL and optional OAICOMPAT_<NAME>_API_KEY.
# The <NAME> becomes the provider identifier used in AGENT_<ROLE>_PROVIDER.
# Example for a local Ollama instance:
# OAICOMPAT_OLLAMA_BASE_URL=http://localhost:11434/v1/chat/completions
# OAICOMPAT_OLLAMA_API_KEY=
# Then set: AGENT_MANAGER_PROVIDER=ollama
```

No real credentials appear anywhere in source code, templates, logs, or API responses.

### Config Validation Summary

At `create_app()` time, `AppConfig.__init__(overrides=config)` merges the supplied `config` dict over `os.environ` before validating the three required variables: `SECRET_KEY`, `AGENT_MANAGER_MODEL`, and `AGENT_MANAGER_PROVIDER`. This means a test can supply all required values through `create_app(config={...})` without touching the shell environment. A missing value raises `ConfigurationError` immediately at startup. All five specialist-role configs default to `"stub"/"stub"` if the key is absent from both `overrides` and `os.environ`. `DATABASE_URL` defaults to `sqlite:///agenthq.db` if absent and is not in `REQUIRED_VARS`.

---

## Testing Architecture

### `tests/conftest.py`

```python
import pytest
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.database import Base
from app import create_app

# All required configuration is supplied directly through create_app(config=...).
# No environment variables need to be set for the test suite to run.
TEST_CONFIG = {
    "TESTING":                True,
    "SECRET_KEY":             "test-secret",
    "DATABASE_URL":           "sqlite:///:memory:",
    "AGENT_MANAGER_MODEL":    "gpt-4o-mini",
    "AGENT_MANAGER_PROVIDER": "openai",
}

@pytest.fixture(scope="function")
def app():
    """
    Fresh Flask app backed by an in-memory SQLite DB for each test function.
    All required config values are passed via create_app(config=TEST_CONFIG),
    which forwards them to AppConfig before required-variable validation occurs.
    No patching of os.environ is required.
    """
    application = create_app(config=TEST_CONFIG)
    yield application

@pytest.fixture(scope="function")
def session(app):
    """
    Plain SQLAlchemy session isolated per test via a savepoint rollback.
    Uses a connection-level transaction so all operations are rolled back after the test.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    sess = Session()
    yield sess
    sess.close()
    transaction.rollback()
    connection.close()

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def mock_llm_router():
    router = MagicMock()
    router.complete.return_value = '{"tasks": []}'  # overridden per test
    return router
```

### Test File Responsibilities

| File | Covers |
|---|---|
| `test_project_service.py` | create_project (valid, empty title, long title), list_projects ordering, update_project_status transitions, project.created event, 409 conflict |
| `test_task_service.py` | create_task (with/without deps), status transitions (valid and invalid), done→cascade to ready, event recording per transition |
| `test_event_service.py` | record() persists event, secret redaction (top-level matching keys, nested depth-2 matching keys, nested depth-3 matching keys, depth-4 keys not redacted), list returns chronological order |
| `test_manager_agent.py` | Valid ProjectPlan → tasks persisted + planning_completed event; invalid JSON → planning_failed + project blocked; provider error → planning_failed; plan with invalid role value → planning_failed + project blocked (no tasks persisted) |
| `test_llm_router.py` | role format validation, prompt length validation, missing config → ConfigurationError, correct provider called, LLMProviderError on failure |
| `test_dependency_resolution.py` | Single prerequisite (remains backlog), multiple prerequisites (all must be done), self-dependency rejected, cycle detection (direct, transitive), evaluate_dependents cascade |
| `test_filesystem_tool.py` | Valid path inside workspace (proceeds), ../ traversal outside (WorkspaceBoundaryError), absolute path outside (WorkspaceBoundaryError) |
| `test_api_routes.py` | HTTP contract tests: status codes, response shapes, UUID validation, Pydantic 422 responses, 404 for unknown resources, 409 for duplicate planning |

### Key Testing Patterns

**Isolated DB per test:** The `session` fixture uses a connection-level transaction that is rolled back after each test, ensuring zero cross-test state.

**Manager Agent tests:** `mock_llm_router.complete.return_value` is set to a JSON string per test case. The three paths — valid plan, invalid JSON, provider error — are tested independently.

**Serialization round-trip (Requirement 13.8):** For each model with a `to_dict()` method, a test verifies that `Model.from_dict(instance.to_dict())` produces an object with equal field values.

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

---

### Property 1: Valid project creation always produces a draft record with an event

*For any* valid (title, description) pair within the allowed character limits, calling `create_project` SHALL produce a `Project` record with `status = "draft"` and SHALL record exactly one `project.created` event containing the project id, title, and status.
**Validates: Requirements 1.1, 1.4**

---

### Property 2: Invalid project input is always rejected without side effects

*For any* project creation request where the title or description is empty, whitespace-only, or exceeds the character limit, the system SHALL reject the request and the total count of `Project` records in the database SHALL remain unchanged.
**Validates: Requirements 1.2, 1.3**

---

### Property 3: Project identifiers are globally unique

*For any* set of N successfully created projects, all N project identifiers SHALL be distinct.
**Validates: Requirements 1.5**

---

### Property 4: Project list is always sorted descending by creation time

*For any* set of persisted projects, `list_projects` SHALL return them in strictly descending order of `created_at` (the most recently created project appears first).
**Validates: Requirements 1.6**

---

### Property 5: Manager planning produces exactly one task per plan entry

*For any* `ProjectPlan` with N tasks (N ≥ 1) that passes Pydantic validation, calling `ManagerAgent.plan()` SHALL persist exactly N `Task` records and record a `manager.planning_completed` event.
**Validates: Requirements 2.4, 2.6**

---

### Property 6: Invalid LLM output always triggers planning failure without task creation

*For any* string that cannot be parsed as a valid `ProjectPlan`, the Manager SHALL persist zero `Task` records, record a `manager.planning_failed` event, and set the project status to `blocked`.
**Validates: Requirements 2.2, 2.3**

---

### Property 7: Task status transitions respect the lifecycle adjacency list

*For any* (current_status, target_status) pair where `target_status` is NOT in `TASK_TRANSITIONS[current_status]`, calling `update_task_status` SHALL raise an `InvalidTransitionError` and the task's status in the database SHALL remain equal to `current_status`.
**Validates: Requirements 3.1, 3.4**

---

### Property 8: Every permitted task status change records exactly one event

*For any* valid task status transition, `update_task_status` SHALL record exactly one `task.status_changed` event containing the task id, previous status, new status, and project id.
**Validates: Requirements 3.5**

---

### Property 9: Task dependency completion cascade promotes all newly unblocked tasks

*For any* task T that transitions to `done`, every dependent task D for which ALL of D's prerequisites now have status `done` SHALL be promoted to `ready`, and exactly one `task.status_changed` event SHALL be recorded for each such promotion.
**Validates: Requirements 3.2, 3.7, 3.8**

---

### Property 10: Tasks with no prerequisites are immediately ready

*For any* task created with zero prerequisite dependencies, the task's status immediately after creation SHALL be `ready` (not `backlog`).
**Validates: Requirements 3.3**

---

### Property 11: Cycle detection prevents any cycle in the dependency graph

*For any* existing set of task dependency edges forming a valid DAG, if adding a new edge `u → v` would create a directed cycle (including self-dependencies), `create_task_dependency` SHALL raise a `ValueError` describing the cycle path and SHALL NOT persist the `TaskDependency` record.
**Validates: Requirements 5.3, 5.4**

---

### Property 12: A task remains in backlog until all prerequisites reach done

*For any* task T with K ≥ 1 prerequisites, T SHALL NOT transition to `ready` status unless every one of its K prerequisites has status `done`. If fewer than K prerequisites are `done`, T SHALL remain in its current status after any prerequisite completes.
**Validates: Requirements 5.5, 5.6**

---

### Property 13: Event payload secret redaction applies recursively to all matching keys within depth 3

*For any* event payload dict containing, at nesting depth 1, 2, or 3, one or more keys whose names match the pattern `(?i)(key|token|secret|password)`, the value stored in the database for each such key SHALL be the string `"[REDACTED]"`, and all non-matching keys at any depth SHALL retain their original values; nested dicts at depth 4 or beyond SHALL be stored as-is without redaction.
**Validates: Requirements 8.8**

---

### Property 14: Workspace boundary enforcement applies to all file paths

*For any* file path argument passed to a filesystem tool, if the resolved absolute path does not begin with the configured workspace root for the active project, the tool SHALL raise a `WorkspaceBoundaryError` and SHALL NOT perform any read or write operation.
**Validates: Requirements 11.3**

---

### Property 15: Service serialization round-trip preserves all fields

*For any* model instance (Project, Task, Event, Message, TaskDependency), calling `instance.to_dict()` followed by constructing a comparable object from that dict SHALL produce an object whose field values compare equal to the original instance on a field-by-field basis.
**Validates: Requirements 13.8**

---

### Property 16: LLM router rejects all out-of-bounds prompts

*For any* string passed to `LLMRouter.complete()` that is either empty or exceeds 32,768 characters, the router SHALL raise a `ValueError` indicating the invalid length and SHALL NOT invoke any provider's `complete()` method.
**Validates: Requirements 7.11**

---

## Error Handling

### Service-Level Exceptions

All domain exceptions inherit from Python builtins to minimize import coupling:

```
RuntimeError
  └── ConfigurationError    (missing env var)
  └── LLMProviderError      (provider failure)

ValueError
  └── InvalidTransitionError (status machine violation)
  └── (validation errors from Pydantic)

PermissionError
  └── WorkspaceBoundaryError (path outside workspace)

LookupError
  └── NotFoundError          (record not found)
```

### Transaction Boundaries

`update_task_status()` is the most complex transaction. The complete sequence — status update, event record, prerequisite cascade, cascade event records — must succeed or fail atomically:

```python
try:
    task.status = new_status
    session.flush()
    event_service.record(session, ...)
    if new_status == TaskStatus.done:
        evaluate_dependents(session, ...)
    session.commit()
except Exception:
    session.rollback()
    raise
```

The route layer catches the raised exception and returns the appropriate HTTP error.

### Partial Planning Failure

If `ManagerAgent.plan()` raises at any point — during the LLM call, Pydantic validation, task persistence, or dependency persistence — `trigger_planning()` catches the exception, rolls back the session to its pre-call state, and re-raises. The route layer catches the raised exception and returns the appropriate HTTP error without performing any session management itself.

This means `POST /api/projects/<project_id>/plan` requires no rollback in the route handler. All session commit/rollback logic for the planning flow lives in `trigger_planning()`.

---

## Testing Strategy

### Dual Testing Approach

Phase 1 uses both example-based unit tests and property-based tests:

- **Unit tests** verify specific scenarios, error paths, and integration between layers
- **Property-based tests** verify universal invariants across generated inputs

### Property-Based Testing Library

[Hypothesis](https://hypothesis.readthedocs.io/) is the standard PBT library for Python and is well-suited to this project. It must be added to `pyproject.toml`:

```toml
[dependency-groups]
dev = [
    "pytest>=9,<10",
    "hypothesis>=6.0,<7",
]
```

Each property-based test is tagged with a comment referencing its design property:

```python
# Feature: agenthq-mvp-phase1, Property 2: Invalid project input is always rejected without side effects
@given(
    title=st.one_of(st.just(""), st.text(alphabet=string.whitespace, min_size=1)),
    description=st.text(min_size=1, max_size=5000),
)
@settings(max_examples=100)
def test_invalid_title_rejected(session, title, description):
    with pytest.raises((ValueError, ValidationError)):
        create_project(session, title, description)
    assert session.query(Project).count() == 0
```

### Test Coverage Targets

| Area | Test Type | File |
|---|---|---|
| Project creation / validation | Property + Example | `test_project_service.py` |
| Project list ordering | Property | `test_project_service.py` |
| Task status machine | Property | `test_task_service.py` |
| Dependency cascade | Property | `test_dependency_resolution.py` |
| Cycle detection | Property | `test_dependency_resolution.py` |
| Event redaction | Property | `test_event_service.py` |
| Manager planning paths | Example (mocked LLM) | `test_manager_agent.py` |
| LLM router validation | Property + Edge case | `test_llm_router.py` |
| Workspace boundary | Property | `test_filesystem_tool.py` |
| Serialization round-trip | Property | `test_project_service.py`, `test_task_service.py` |
| HTTP contract | Example | `test_api_routes.py` |
| All task lifecycle states | Example | `test_task_service.py` |
| All project lifecycle states | Example | `test_project_service.py` |

### Unit Test Principles

- Focus unit tests on: specific error messages, integration points (route→service), event payload contents
- Avoid duplicating coverage that property tests already provide with many inputs
- All DB-dependent tests use in-memory SQLite with rollback-per-test isolation
- Manager Agent tests always mock `LLMRouter` to avoid real API calls

---

## Implementation Order

Follow AGENTS.md priority order. Each step builds on the one before it with no skipping forward.

1. **`app/exceptions.py`** — Define all custom exception classes first. Nothing else depends on import ordering here, and everything else imports from this module.

2. **`app/constants.py`** — `AgentRole`, `ProjectStatus`, `TaskStatus`, `TaskPriority`, `EventName`, `TASK_TRANSITIONS`, `PROJECT_TRANSITIONS`. No imports from the app.

3. **`app/config.py`** — `AppConfig` class. Imports constants and exceptions only.

4. **`app/models/database.py`** — `Base` (DeclarativeBase), `get_engine()`, `get_session_factory()`, `get_db()`. No Flask-SQLAlchemy. Imports only `sqlalchemy` (already in pyproject.toml).

5. **`app/models/`** — All five models: `project.py`, `task.py`, `task_dependency.py`, `event.py`, `message.py`. Import `db` from `database.py`. Add `to_dict()` methods.

6. **`app/models/__init__.py`** — Re-export `db` and all models.

7. **`app/schemas.py`** — `ModelConfig`, `AgentResult`, `ProjectPlan`, `PlanTask`, all request schemas. Imports constants only.

8. **`app/llm/base.py`** — `BaseLLMProvider` abstract class. No app imports.

9. **`app/llm/providers/openai_provider.py`**, **`anthropic_provider.py`**, **`gemini_provider.py`**, **`openai_compatible_provider.py`** — Four concrete providers, all using `httpx`. The three named providers read credentials from fixed env vars; `OpenAICompatibleProvider` accepts `base_url`, `api_key`, and `provider_name` as constructor arguments for use with any OpenAI-compatible endpoint. Add `httpx>=0.27,<1` to `pyproject.toml` at this step.

10. **`app/llm/router.py`** — `LLMRouter`. Imports base, exceptions.

11. **`app/llm/__init__.py`**, **`app/llm/providers/__init__.py`** — Exports and `build_provider_registry()`.

12. **`app/agents/base.py`** — `BaseAgent` abstract class. Imports constants, schemas only.

13. **`app/agents/manager.py`** — `ManagerAgent`. Imports base, schemas, constants, exceptions. Services injected; no direct DB import.

14. **`app/agents/designer.py`, `frontend.py`, `backend.py`, `qa.py`, `utility.py`** — Stub agents.

15. **`app/agents/__init__.py`** — `AGENT_REGISTRY`, `build_registry()`.

16. **`app/services/event_service.py`** — `EventService`. Imports models, constants. No circular deps.

17. **`app/services/task_service.py`** — `TaskService`. Imports models, constants, exceptions, event_service.

18. **`app/services/project_service.py`** — `ProjectService`. Imports models, constants, exceptions, event_service. Imports task_service for planning flow.

19. **`app/tools/filesystem.py`** — `FilesystemTool`. Imports exceptions only.

20. **`app/routes/helpers.py`** — UUID validation, `json_error()`. Flask imports here only.

21. **`app/routes/api.py`** — API Blueprint. Imports route helpers, services, schemas. No direct model imports.

22. **`app/routes/ui.py`** — UI Blueprint. Imports services.

23. **`app/__init__.py`** — `create_app()`. Assembles everything.

24. **`templates/`** — `base.html`, then `dashboard.html`, `project_form.html`, `project_detail.html`.

25. **`static/js/main.js`**, **`static/css/main.css`** — Minimal vanilla JS and CSS.

26. **`tests/conftest.py`** — Fixtures.

27. **`tests/test_*.py`** — All test files. Write alongside each feature as it is implemented, not after.

28. **`.env.example`** — All required variable names with placeholder values.

**New dependencies vs original design:**
- `flask-sqlalchemy` — REMOVED. Plain `sqlalchemy` (already in pyproject.toml) is sufficient.
- `openai` SDK — REMOVED. `httpx` handles all three provider HTTP calls directly.
- `httpx>=0.27,<1` — ADDED. Required for OpenAI, Anthropic, and Gemini provider implementations.
- `hypothesis>=6.0,<7` — ADDED (dev). Required for property-based tests.

**Rationale for ordering:** Exceptions and constants have no inbound deps from app code, so they are safe to write first. Models depend on the db instance but nothing else from the app. Schemas depend on constants. LLM layer has no app deps beyond exceptions. Agents depend on LLM layer and schemas but not on services or Flask. Services depend on models and constants but not Flask. Routes are the outermost layer and are written last. Tests are written alongside each layer using the fixtures from conftest.
