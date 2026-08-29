# Requirements Document

## Introduction

AgentHQ MVP Phase 1 establishes the foundational backend and UI infrastructure for an autonomous AI software company. The user acts as CEO and submits software projects through a web interface. A Manager Agent, backed by a real LLM call, analyzes the requirement, produces a structured project plan, and persists tasks with dependencies in SQLite. All project, task, agent, and event state is stored in the database. Flask routes expose this state via REST API and Jinja2-rendered UI pages. Phase 1 does not execute specialist agents (designer, frontend, backend, QA); it creates the complete, stable foundation on which they can be added in Phase 2.

---

## Glossary

- **CEO**: The human user operating the AgentHQ system through the web interface.
- **Project**: A software deliverable submitted by the CEO, with lifecycle states `draft → planning → in_progress → review → blocked → delivered → cancelled`.
- **Manager_Agent**: The LLM-backed agent responsible for analyzing project requirements, producing a structured plan, and creating tasks.
- **Specialist_Agent**: A future agent role (designer, frontend, backend, qa, utility) that receives and executes tasks. Not executed in Phase 1.
- **Task**: A discrete unit of work within a project, with lifecycle states `backlog → ready → in_progress → review → blocked → rework → done`.
- **TaskDependency**: A directed edge between two Tasks indicating that the dependent task cannot enter `ready` state until its prerequisite reaches `done`.
- **AgentRole**: An enumeration of valid agent roles: `manager`, `designer`, `frontend`, `backend`, `qa`, `utility`.
- **Event**: An immutable record of a meaningful system state transition, stored in the database with a typed name, payload, and timestamp.
- **LLM_Router**: The internal component that accepts a prompt and model configuration and dispatches to the configured provider, returning raw text or a structured response.
- **LLM_Provider**: A concrete adapter (e.g., OpenAI, Anthropic) implementing the provider interface consumed by the LLM_Router.
- **ProjectPlan**: A Pydantic-validated structured object produced by the Manager_Agent containing a list of tasks with titles, descriptions, assigned roles, priorities, and dependency references.
- **Workspace**: The isolated directory `workspace/<project-id>/` in which all project artifacts must reside.
- **Activity_Feed**: The UI component that renders Event records for a project in chronological order.
- **BaseAgent**: The abstract Python class all agents must implement.
- **Service**: A Python module containing business logic that coordinates between models, agents, tools, and the database session; it has no Flask dependency.
- **Route**: A Flask Blueprint function that handles HTTP requests and delegates to Services; it contains no business logic.

---

## Requirements

### Requirement 1: Project Creation

**User Story:** As a CEO, I want to submit a new software project with a title and description, so that the Manager Agent can begin planning.

#### Acceptance Criteria

1. WHEN the CEO submits a valid project creation form containing a title between 1 and 200 characters and a description between 1 and 5000 characters, THE System SHALL persist a `Project` record with status `draft` and return the project identifier to the client within 2 seconds.
2. WHEN the CEO submits a project creation form with an empty title or empty description, THE System SHALL return a 400 response with a structured error message identifying which field or fields failed validation, without persisting any record.
3. WHEN the CEO submits a project creation form with a title exceeding 200 characters or a description exceeding 5000 characters, THE System SHALL return a 400 response with a structured error message identifying the field that exceeded its limit, without persisting any record.
4. WHEN a `Project` record is created, THE System SHALL immediately persist an `Event` record with name `project.created` containing the project identifier, title, and status before returning the response to the client.
5. THE System SHALL assign a globally unique identifier to each `Project` at creation time such that no two projects share the same identifier.
6. WHEN the CEO views the project list page, THE System SHALL render all persisted projects displaying their current status, title, and creation timestamp in descending order of creation timestamp.
7. WHEN the CEO views a single project detail page and the project identifier exists, THE System SHALL render the project title, description, status, creation timestamp, task list, and activity feed for that project.
8. IF the project identifier in a single project detail page request does not match any persisted `Project` record, THEN THE System SHALL return a 404 response with an error message indicating the project was not found.
9. IF a database error occurs during project creation, THEN THE System SHALL return a 500 response with an error message that does not expose internal stack traces or database details, and shall not persist a partial `Project` record.

---

### Requirement 2: Manager Agent Planning

**User Story:** As a CEO, I want the Manager Agent to automatically analyze my project requirement and produce a structured plan with tasks and dependencies, so that work can be organized without manual decomposition.

#### Acceptance Criteria

1. WHEN a project transitions to `planning` status, THE Manager_Agent SHALL invoke the LLM_Router with the project title and description as input and the manager role's configured model.
2. WHEN the LLM_Router returns a response, THE Manager_Agent SHALL validate the raw output against the `ProjectPlan` Pydantic schema before any application logic acts on it.
3. IF the LLM_Router response cannot be parsed into a valid `ProjectPlan`, THEN THE Manager_Agent SHALL record an `Event` with name `manager.planning_failed` containing an error description that does not include raw model output or provider internals, and transition the project to `blocked` status.
4. WHEN the `ProjectPlan` passes validation and contains one or more tasks, THE Manager_Agent SHALL persist one `Task` record per plan entry, each with title, description, assigned `AgentRole`, priority, and status `backlog`; IF the validated plan contains zero tasks, THE Manager_Agent SHALL treat this as a planning failure and record `manager.planning_failed`.
5. WHEN the `ProjectPlan` specifies a dependency between two tasks, THE Manager_Agent SHALL persist a `TaskDependency` record linking the prerequisite task to the dependent task; IF a dependency references a task identifier not present in the current plan, THE Manager_Agent SHALL skip that dependency and record a warning in the `manager.planning_completed` event payload.
6. WHEN planning completes successfully, THE Manager_Agent SHALL transition the project to `in_progress` status and record an `Event` with name `manager.planning_completed` containing the project identifier and task count.
7. WHEN the Manager_Agent begins planning, THE System SHALL record an `Event` with name `manager.planning_started` containing the project identifier.
8. THE Manager_Agent SHALL NOT directly execute database writes; all persistence SHALL be delegated to the Project_Service or Task_Service.
9. THE Manager_Agent SHALL NOT hard-code any LLM provider name or API key inside its implementation.
10. WHEN the Manager_Agent produces a `ProjectPlan`, THE System SHALL validate every field via Pydantic before any persistence occurs; IF any `assigned_role` value is not a member of the `AgentRole` enumeration, THEN Pydantic validation SHALL fail, THE Manager_Agent SHALL treat this as a planning failure, record `manager.planning_failed`, transition the project to `blocked`, and persist zero tasks.
11. IF a planning run is triggered on a project that already has status `planning` or `in_progress`, THEN THE System SHALL return a 409 response indicating the project is already being planned and SHALL NOT start a second planning run.

---

### Requirement 3: Task Lifecycle Management

**User Story:** As a CEO, I want tasks to progress through defined lifecycle states, so that the system accurately reflects the status of all work.

#### Acceptance Criteria

1. THE System SHALL enforce the task lifecycle: `backlog → ready → in_progress → review → done`, with `blocked` reachable from `in_progress` and `rework` reachable from `review`, where `blocked` may only return to `in_progress` and `rework` may only return to `in_progress` or advance to `done`.
2. WHEN a `Task` is in `backlog` status and all of its prerequisite tasks have reached `done` status, THE Task_Service SHALL transition the task to `ready` status within one evaluation cycle of the final prerequisite reaching `done`.
3. WHEN a `Task` has no prerequisites, THE Task_Service SHALL transition the task from `backlog` to `ready` status before the task creation response is returned to the caller.
4. IF a task status transition is requested for a transition not permitted by the lifecycle, THEN THE System SHALL return a 422 response with a structured error body identifying the task identifier, the current status, and the disallowed target status, without modifying the task record.
5. WHEN a `Task` status changes, THE System SHALL record an `Event` with name `task.status_changed` containing the task identifier, previous status, new status, and project identifier before the status-change response is returned to the caller.
6. THE System SHALL expose a PATCH endpoint at `/api/projects/<project_id>/tasks/<task_id>/status` that accepts a target status value from the set `{backlog, ready, in_progress, review, done, blocked, rework}`, validates the transition, and delegates to the Task_Service.
7. WHEN a `Task` transitions to `done`, THE Task_Service SHALL evaluate all tasks in the same project that list the completed task as a prerequisite and transition any task whose every prerequisite has `done` status to `ready` status.
8. WHEN one or more dependent tasks transition to `ready` as a result of a prerequisite completion, THE System SHALL record a `task.status_changed` event for each such transition before the originating status-change response is returned to the caller.
9. IF the prerequisite evaluation triggered by a `done` transition fails due to a database error, THEN THE System SHALL roll back the originating task's status change, retain the task's previous status, and return a 500 response with an error message indicating the evaluation failure.

---

### Requirement 4: Task Assignment to Agent Roles

**User Story:** As a CEO, I want tasks to be assigned to the appropriate agent role, so that specialist agents can be dispatched to the right work in a future phase.

#### Acceptance Criteria

1. THE System SHALL require every `Task` to have an `assigned_role` value from the `AgentRole` enumeration at creation time.
2. WHEN the Task_Service creates a task, THE System SHALL validate that `assigned_role` is a member of `AgentRole`; IF the value is not valid, THEN THE System SHALL reject the request with a validation error message indicating the invalid role and shall not persist the task.
3. WHEN a GET request is made to `/api/projects/<project_id>/tasks`, THE System SHALL return all tasks for the specified project, each including `id`, `title`, `description`, `status`, `assigned_role`, `priority`, and dependency identifiers.
4. IF the specified `project_id` in a GET request to `/api/projects/<project_id>/tasks` does not exist, THEN THE System SHALL return an error response indicating the project was not found.
5. WHEN a GET request is made to `/api/projects/<project_id>/tasks/<task_id>`, THE System SHALL return the full detail of the specified task including its prerequisite task identifiers and dependent task identifiers.
6. IF the specified `task_id` in a GET request to `/api/projects/<project_id>/tasks/<task_id>` does not exist or does not belong to the specified project, THEN THE System SHALL return an error response indicating the task was not found.
7. WHERE a future specialist agent implementation is added, THE BaseAgent interface SHALL allow the agent to be associated with an `AgentRole` and queried for task eligibility without modifying existing task or project models.

---

### Requirement 5: Dependency Resolution

**User Story:** As a CEO, I want task dependencies to be respected automatically, so that tasks are only worked on when their prerequisite work is complete.

#### Acceptance Criteria

1. THE System SHALL persist directed dependency edges as `TaskDependency` records where `prerequisite_task_id` and `dependent_task_id` reference valid tasks within the same project.
2. IF a `TaskDependency` creation request references a task identifier that does not exist within the specified project, THEN THE System SHALL return an error response indicating the task was not found and not persist the dependency record.
3. IF a `TaskDependency` creation would form a cycle (task A depends on task B which already depends on task A directly or transitively), THEN THE System SHALL return an error response with a description of the detected cycle path and not persist the dependency record.
4. IF a `TaskDependency` creation request specifies the same task as both `prerequisite_task_id` and `dependent_task_id`, THEN THE System SHALL return an error response indicating self-dependency is not allowed and not persist the dependency record.
5. WHEN the `Task_Service` evaluates whether a task can transition to `ready`, THE `Task_Service` SHALL query all `TaskDependency` records where `dependent_task_id` matches the task and confirm every prerequisite task has `done` status before allowing the transition.
6. IF the `Task_Service` evaluates a task's prerequisites and at least one prerequisite task does not have `done` status, THEN THE `Task_Service` SHALL not transition the task to `ready` and shall retain the task in its current status.
7. WHEN a `GET` request is made to the task dependencies endpoint for a valid task within a valid project, THE System SHALL return a response containing the list of prerequisite tasks (where the specified task is the `dependent_task_id`) and the list of dependent tasks (where the specified task is the `prerequisite_task_id`).
8. IF a `GET` request is made to the task dependencies endpoint referencing a `task_id` or `project_id` that does not exist, THEN THE System SHALL return an error response indicating the resource was not found.

---

### Requirement 6: Agent Abstraction Contract

**User Story:** As a developer, I want a stable `BaseAgent` abstract interface, so that specialist agents can be added in Phase 2 without redesigning the core infrastructure.

#### Acceptance Criteria

1. THE System SHALL define a `BaseAgent` abstract class in `app/agents/base.py` with the following required attributes: `name: str`, `role: AgentRole`, `model_config: ModelConfig`; the `AgentRole` enumeration SHALL define exactly the values: `manager`, `designer`, `frontend`, `backend`, `qa`, `utility`.
2. THE `BaseAgent` SHALL define an abstract method `run(task: Task, context: dict) -> AgentResult` that all concrete agents must implement.
3. THE System SHALL define a `ModelConfig` Pydantic model containing at minimum `provider: str` and `model: str` fields, sourced from environment configuration rather than hard-coded values.
4. THE System SHALL define an `AgentResult` Pydantic model containing at minimum `status: str` (valid values: `success`, `failure`, `not_implemented`), `output: dict`, and `error: str | None` fields.
5. WHEN a concrete agent's `run` method returns a value, THE System SHALL validate the return value against the `AgentResult` Pydantic schema; IF validation fails, THE System SHALL raise a `ValueError` identifying the agent role and the validation error before any downstream logic processes the result.
6. THE `Manager_Agent` SHALL be a concrete implementation of `BaseAgent` with `role = AgentRole.manager`.
7. THE `BaseAgent` interface SHALL NOT import Flask, SQLAlchemy sessions, or route-layer objects; it SHALL accept all persistence-related context through its constructor or the `run` method parameters.
8. THE System SHALL provide stub concrete agent classes for `designer`, `frontend`, `backend`, `qa`, and `utility` roles in Phase 1, each implementing `run` and returning an `AgentResult` with `status = "not_implemented"`, `output = {}`, and `error = "Agent <role> is not yet implemented"`.

---

### Requirement 7: LLM Provider Abstraction

**User Story:** As a developer, I want all LLM calls to go through a provider-agnostic router, so that the underlying model or provider can be changed per role without touching agent business logic.

#### Acceptance Criteria

1. THE System SHALL define a `BaseLLMProvider` abstract class in `app/llm/base.py` with an abstract method `complete(prompt: str, model: str, **kwargs) -> str`.
2. THE LLM_Router SHALL accept a role identifier string of 1 to 64 characters containing only uppercase letters and underscores, a prompt string of 1 to 32,768 characters, and optional keyword arguments; it SHALL resolve the correct provider and model from environment configuration and delegate to the appropriate `BaseLLMProvider` implementation.
3. THE System SHALL read model-per-role configuration from environment variables using the naming convention `AGENT_<ROLE>_MODEL` (e.g., `AGENT_MANAGER_MODEL`) and `AGENT_<ROLE>_PROVIDER` (e.g., `AGENT_MANAGER_PROVIDER`).
4. IF an environment variable for a required role model or provider is not set, THEN THE LLM_Router SHALL raise a `ConfigurationError` naming the missing variable and not make any API call.
5. THE LLM_Router SHALL NOT log prompt contents, raw LLM responses, or API keys at any log level.
6. WHEN the LLM_Router receives a raw string response from a provider, THE LLM_Router SHALL return that raw string to the calling agent without modification; structured output parsing SHALL be the agent's responsibility.
7. THE System SHALL provide at least one concrete `BaseLLMProvider` implementation in `app/llm/providers/` that fully implements the `BaseLLMProvider` abstract interface.
8. THE System SHALL expose a provider registry in `app/llm/router.py` that maps provider name strings to `BaseLLMProvider` instances, populated at application startup from configuration.
9. IF the LLM provider returns a non-success response or raises a network exception, THEN THE LLM_Router SHALL raise an `LLMProviderError` with a message indicating the provider name and failure category (e.g., network error, rate limit, auth failure) and not expose the raw response body to the caller.
10. IF the LLM_Router receives a role identifier that is not registered in the provider registry, THEN THE LLM_Router SHALL raise a `ConfigurationError` naming the unrecognised role and not make any API call.
11. IF the prompt string passed to the LLM_Router is empty or exceeds 32,768 characters, THEN THE LLM_Router SHALL raise a `ValueError` indicating the invalid prompt length and not make any API call.

---

### Requirement 8: Event and Activity System

**User Story:** As a CEO, I want every important state transition to be recorded as an event, so that I can review the full activity history of a project.

#### Acceptance Criteria

1. THE System SHALL define an `Event` model with fields: `id`, `project_id`, `event_name`, `payload` (JSON), `created_at`, and an optional `task_id`; the `payload` field SHALL store only serializable primitive values (strings, numbers, booleans, null) and SHALL NOT store binary data, function references, or nested objects deeper than three levels.
2. THE Event_Service SHALL provide a `record(project_id, event_name, payload, task_id=None)` function that persists an `Event` record within the active database session; IF the database write fails, THE Event_Service SHALL raise a `RuntimeError` with a message indicating the event name and project identifier.
3. THE System SHALL record events for the following transitions at minimum: `project.created`, `project.status_changed`, `manager.planning_started`, `manager.planning_completed`, `manager.planning_failed`, `task.created`, `task.status_changed`.
4. THE System SHALL expose a GET endpoint at `/api/projects/<project_id>/events` returning all events for a project ordered by `created_at` ascending, each including `id`, `event_name`, `payload`, `created_at`, and `task_id`; IF the specified `project_id` does not exist, THE System SHALL return a 404 response.
5. WHEN the CEO views the project detail page, THE System SHALL render an Activity_Feed section displaying all events for that project in chronological order, showing a human-readable summary derived from `event_name` and the safe fields of `payload`; safe fields are defined as any payload field whose key does not match the pattern `.*key.*`, `.*token.*`, `.*secret.*`, or `.*password.*` (case-insensitive).
6. THE Activity_Feed SHALL NOT display raw LLM chain-of-thought, API keys, internal stack traces, or raw JSON strings; if a payload value is a JSON object, THE System SHALL render only a structured summary of its top-level keys and their primitive values.
7. THE Event_Service SHALL be callable from Services only; Routes SHALL NOT call Event_Service directly but SHALL delegate to the appropriate Service which records events as part of its transaction.
8. WHEN an event payload would contain a key matching the pattern `.*key.*`, `.*token.*`, `.*secret.*`, or `.*password.*` (case-insensitive), THE Event_Service SHALL replace that key's value with the string `[REDACTED]` before persisting.

---

### Requirement 9: Flask API and UI Routes

**User Story:** As a CEO, I want a web UI and REST API that expose real system state, so that I can monitor projects and tasks accurately.

#### Acceptance Criteria

1. THE System SHALL register all API endpoints under the `/api` prefix using Flask Blueprints.
2. THE System SHALL register all UI page routes using a separate Flask Blueprint.
3. THE System SHALL expose the following API endpoints:
   - `POST /api/projects` — create a project
   - `GET /api/projects` — list all projects
   - `GET /api/projects/<project_id>` — get project detail
   - `PATCH /api/projects/<project_id>/status` — update project status
   - `GET /api/projects/<project_id>/tasks` — list tasks for a project
   - `GET /api/projects/<project_id>/tasks/<task_id>` — get task detail
   - `PATCH /api/projects/<project_id>/tasks/<task_id>/status` — update task status
   - `GET /api/projects/<project_id>/tasks/<task_id>/dependencies` — get task dependencies
   - `GET /api/projects/<project_id>/events` — list events for a project
   - `POST /api/projects/<project_id>/plan` — trigger Manager planning for a project
4. THE System SHALL expose the following UI page routes:
   - `GET /` — dashboard listing all projects with status summary
   - `GET /projects/new` — project creation form
   - `GET /projects/<project_id>` — project detail with task list and activity feed
5. WHEN an API endpoint receives a request body, THE Route SHALL validate the request against a Pydantic request schema before passing data to the Service; IF validation fails, THE Route SHALL return a 422 response with field-level error details identifying each invalid field by name and the reason it failed validation.
6. WHEN an API endpoint completes successfully, THE Route SHALL return a JSON response body with an HTTP status code in the range 200–299.
7. WHEN an API endpoint receives a `project_id` or `task_id` that does not exist in the database, THE Route SHALL return a 404 JSON response containing an error message indicating which resource was not found.
8. THE Route layer SHALL contain no business logic; all logic SHALL be delegated to Services.
9. WHILE the backend has no real activity for a project (no tasks, no events), THE UI SHALL render an explicit empty state message rather than fabricated data.
10. THE System SHALL return all API timestamps in ISO 8601 UTC format (e.g. `YYYY-MM-DDTHH:MM:SSZ`).
11. IF an unhandled exception occurs during API request processing, THE System SHALL return a 500 JSON response containing an error message indicating an internal error occurred, without exposing internal exception details or stack traces.
12. WHEN `POST /api/projects` receives a request body, THE Route SHALL reject any `title` value exceeding 200 characters and any `description` value exceeding 5000 characters with a 422 response.
13. WHEN `PATCH /api/projects/<project_id>/status` or `PATCH /api/projects/<project_id>/tasks/<task_id>/status` receives a status value, THE Route SHALL reject any value not belonging to the defined set of valid project or task statuses respectively, returning a 422 response with an error message indicating the rejected value and the list of accepted values.

---

### Requirement 10: Data Models and Persistence

**User Story:** As a developer, I want well-defined SQLAlchemy models with explicit relationships, so that state is reliably persisted and the schema can be migrated to PostgreSQL without rewriting business logic.

#### Acceptance Criteria

1. THE System SHALL define the following SQLAlchemy models in `app/models/`: `Project`, `Task`, `TaskDependency`, `Event`, `Message`.
2. THE `Project` model SHALL include: `id` (UUID string), `title` (non-nullable string with a maximum length of 255 characters), `description` (non-nullable text), `status` (non-nullable string, constrained to project lifecycle values: `draft`, `planning`, `in_progress`, `review`, `blocked`, `delivered`, `cancelled`), `created_at` (non-nullable datetime, UTC), `updated_at` (non-nullable datetime, UTC).
3. THE `Task` model SHALL include: `id` (UUID string), `project_id` (foreign key to `Project.id`), `title` (non-nullable string with a maximum length of 255 characters), `description` (text), `assigned_role` (non-nullable string, constrained to `AgentRole` values), `priority` (non-nullable string, values: `low`, `medium`, `high`), `status` (non-nullable string, constrained to task lifecycle values: `backlog`, `ready`, `in_progress`, `review`, `blocked`, `rework`, `done`), `created_at`, `updated_at`.
4. THE `TaskDependency` model SHALL include: `id` (UUID string), `project_id` (foreign key to `Project.id`), `prerequisite_task_id` (foreign key to `Task.id`), `dependent_task_id` (foreign key to `Task.id`), `created_at`; the combination of `prerequisite_task_id` and `dependent_task_id` SHALL be unique.
5. THE `Event` model SHALL include: `id` (UUID string), `project_id` (foreign key to `Project.id`), `task_id` (nullable foreign key to `Task.id`), `event_name` (non-nullable string with a maximum length of 255 characters), `payload` (stored using a column type compatible with both SQLite and PostgreSQL), `created_at`.
6. THE `Message` model SHALL include: `id` (UUID string), `project_id` (foreign key to `Project.id`), `task_id` (nullable foreign key to `Task.id`), `sender_role` (non-nullable string with a maximum length of 100 characters), `message_type` (non-nullable string with a maximum length of 100 characters), `body` (non-nullable text), `created_at`.
7. THE System SHALL initialize the database schema via a `db.create_all()` call during application startup using SQLAlchemy's declarative base.
8. THE System SHALL use string UUIDs as primary keys rather than auto-increment integers, so that identifiers are portable and do not expose record counts; UUID values SHALL be generated server-side at record creation time.
9. THE System SHALL NOT use SQLite-specific column types or behaviors (e.g., no `ROWID` assumptions, JSON stored as `Text` or using `JSON` type that is portable to PostgreSQL).
10. THE System SHALL define all model relationships using SQLAlchemy `relationship()` with explicit `foreign_keys` arguments where ambiguity exists, to preserve correctness when migrating to PostgreSQL.
11. IF a database operation violates a model constraint (non-nullable field, invalid status value, or foreign key reference to a non-existent record), THEN THE System SHALL raise a validation error before the write is committed and leave the database state unchanged.
12. WHEN a `Project` record is deleted, THE System SHALL delete all associated `Task`, `TaskDependency`, `Event`, and `Message` records via cascade, so that no orphaned child records remain.

---

### Requirement 11: Security Constraints

**User Story:** As a developer, I want security constraints enforced at the system boundary, so that secrets are never exposed and filesystem access is restricted to project workspaces.

#### Acceptance Criteria

1. THE System SHALL load all API keys and provider credentials exclusively from environment variables via `python-dotenv`; no key or credential SHALL appear in source code, templates, logs, or API responses.
2. THE System SHALL provide a `.env.example` file listing all required environment variable names with placeholder values and without real credentials.
3. WHEN any filesystem tool operates on a file path, THE Tool SHALL resolve the absolute path and verify it begins with the configured workspace root (`workspace/<project_id>/`) before performing any read or write; IF the path falls outside the workspace, THE Tool SHALL raise a `WorkspaceBoundaryError`, return a structured error response indicating the boundary violation, and not perform the operation.
4. THE System SHALL NOT expose Python exception stack traces in API responses or UI pages; error responses SHALL contain only a safe message string of no more than 200 characters and a single error code string.
5. WHEN a route receives user-supplied path components (project_id, task_id), THE Route SHALL validate that each is a valid UUID4 string matching the pattern `xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx` before passing it to the Service layer; IF validation fails, THE Route SHALL return a 400 response with a structured error body indicating which field failed validation.
6. THE System SHALL log tool invocations (tool name, project_id, timestamp) at INFO level without logging argument values that may contain secret data; argument values SHALL be omitted or replaced with a fixed placeholder string of no more than 8 characters in the log entry.
7. IF a command execution tool is invoked, THEN THE Tool SHALL check the requested command against a statically defined allowlist of permitted command names before executing; IF the command name is not present in the allowlist, THE Tool SHALL return a structured error response indicating the command was rejected and not execute the command.
8. IF a filesystem tool raises a `WorkspaceBoundaryError`, THEN THE System SHALL log the attempted path and the configured workspace root at WARN level without logging any file content.

---

### Requirement 12: Application Initialization and Configuration

**User Story:** As a developer, I want the Flask application to initialize cleanly with all required configuration, so that a missing variable causes a loud failure at startup rather than a silent runtime error.

#### Acceptance Criteria

1. THE System SHALL define an application factory function `create_app(config=None)` in `app/__init__.py` that registers all Blueprints, initialises the SQLAlchemy database binding, and loads configuration before returning a Flask application instance; THE returned instance SHALL have all routes registered and the database binding active.
2. WHEN the application starts, THE System SHALL validate that the following environment variables are present: `SECRET_KEY`, `DATABASE_URL`, `AGENT_MANAGER_MODEL`, `AGENT_MANAGER_PROVIDER`, `AGENT_DESIGNER_MODEL`, `AGENT_DESIGNER_PROVIDER`, `AGENT_FRONTEND_MODEL`, `AGENT_FRONTEND_PROVIDER`, `AGENT_BACKEND_MODEL`, `AGENT_BACKEND_PROVIDER`, `AGENT_QA_MODEL`, `AGENT_QA_PROVIDER`, `AGENT_UTILITY_MODEL`, `AGENT_UTILITY_PROVIDER`; IF any variable is absent, THE System SHALL raise a `ConfigurationError` at startup naming the first missing variable.
3. THE System SHALL configure SQLAlchemy using the `DATABASE_URL` environment variable; IF `DATABASE_URL` is not set, THE System SHALL default to `sqlite:///agenthq.db` for local development without raising an error.
4. THE System SHALL configure Flask's `SECRET_KEY` from the `SECRET_KEY` environment variable; IF the variable is absent, THE System SHALL raise a `ConfigurationError` at startup with the message identifying `SECRET_KEY` as the missing variable.
5. THE System SHALL register the `api` and `ui` Blueprints within the application factory; WHEN `create_app` returns, a test client created from the returned app SHALL be able to issue a GET request to `/` and receive a non-500 response.
6. THE System SHALL define the `ConfigurationError` class in `app/exceptions.py` as a subclass of `RuntimeError`, carrying the name of the missing or misconfigured variable as a string attribute `variable_name`.

---

### Requirement 13: Testing Strategy

**User Story:** As a developer, I want automated tests covering services, agent abstraction, LLM validation, and database state transitions, so that regressions are caught before deployment.

#### Acceptance Criteria

1. THE Test Suite SHALL include pytest-based unit tests in `tests/` covering the following areas at minimum: project creation service, task lifecycle transitions, dependency resolution (including cycle detection), event recording, and Manager Agent planning logic.
2. WHEN testing the Manager_Agent, THE Test Suite SHALL mock the LLM_Router and test three paths: (a) valid `ProjectPlan` response — assert tasks are persisted and `manager.planning_completed` event is recorded; (b) invalid/unparseable response — assert no tasks are persisted and `manager.planning_failed` event is recorded; (c) provider error — assert no tasks are persisted and the planning service surfaces the error to the caller.
3. WHEN testing task lifecycle transitions, THE Test Suite SHALL include both a nominal path (valid transition results in the task reaching the expected target status) and an error path (invalid transition returns the correct error without mutating the task record).
4. WHEN testing dependency resolution, THE Test Suite SHALL include at minimum: a task with one prerequisite (task remains in `backlog` until prerequisite reaches `done`), a task with two or more prerequisites (task remains in `backlog` until all prerequisites reach `done`), and a cycle-detection case (cycle creation attempt returns an error and no `TaskDependency` record is persisted).
5. THE Test Suite SHALL use an in-memory SQLite database (`:memory:`) for all database-dependent tests, with a fresh database instance created per test function to eliminate cross-test state pollution.
6. THE Test Suite SHALL test the `ProjectPlan` Pydantic validator with: a well-formed plan (validation passes), a plan with an invalid role value (validation fails referencing the `AgentRole` enumeration), a plan with a missing required field (validation fails identifying the missing field), and a plan where task dependencies reference identifiers absent from the same plan (validation or service layer reports the dangling reference).
7. THE Test Suite SHALL test the workspace boundary enforcement in filesystem tools with: a valid path inside the workspace (operation proceeds without error), a path using `../` traversal that resolves outside the workspace root (raises `WorkspaceBoundaryError`), and an absolute path that resolves outside the workspace root (raises `WorkspaceBoundaryError`).
8. FOR ALL service functions that serialize model data to dict representations, THE Test Suite SHALL include a round-trip property: calling the serialize function then the deserialize function SHALL produce an object whose fields compare equal to the original on a field-by-field basis.

---

### Requirement 14: Phase 1 Acceptance Criteria (Definition of Done)

**User Story:** As a CEO, I want Phase 1 to be verifiably complete, so that Phase 2 specialist agent work can begin on a stable foundation.

#### Acceptance Criteria

1. WHEN the CEO submits a project via the UI and the server is running with a valid `.env` file, THE System SHALL persist the project, trigger Manager planning, and render the resulting task list on the project detail page — with no code edits, database migrations, or CLI commands required beyond `flask run`.
2. WHEN the Manager_Agent completes planning, THE System SHALL have persisted at minimum one `Task` record and one `Event` record with name `manager.planning_completed` in the database, verifiable by querying the API endpoints defined in Requirement 9.
3. WHEN the CEO views the project detail page, THE System SHALL render tasks with their current status and all activity events in chronological order, with no fabricated or hard-coded data.
4. WHEN a task's prerequisite is manually transitioned to `done` via the API, THE System SHALL automatically transition the dependent task to `ready` and record exactly two `task.status_changed` events — one for the prerequisite transition and one for the dependent task promotion.
5. THE System SHALL pass all unit tests in `tests/` without failures before Phase 1 is considered complete.
6. THE System SHALL start without error when `SECRET_KEY`, `DATABASE_URL`, and all `AGENT_<ROLE>_MODEL` / `AGENT_<ROLE>_PROVIDER` variables for the six roles defined in Requirement 6 are set in a `.env` file matching `.env.example`.
7. THE System SHALL have stub agent implementations for all six `AgentRole` values, each registered in the agent module and returning an `AgentResult` with `status = "not_implemented"`, `output = {}`, and `error = "Agent <role> is not yet implemented"`.
8. WHEN a developer adds a new `BaseLLMProvider` subclass and registers it in the provider registry under a new provider name string, THE System SHALL route LLM calls for any role whose `AGENT_<ROLE>_PROVIDER` is set to that provider name to the new provider — confirmed by a test that asserts the correct provider's `complete` method is called without any changes to agent business logic files.
9. THE System SHALL NOT contain any hard-coded API keys, model names, or provider names outside of environment variable loading code or `.env.example`.
10. WHEN Phase 1 is complete, EVERY project lifecycle state (`draft`, `planning`, `in_progress`, `review`, `blocked`, `delivered`, `cancelled`), task lifecycle state (`backlog`, `ready`, `in_progress`, `review`, `blocked`, `rework`, `done`), and event type defined in this document SHALL have at least one corresponding automated test asserting correct behavior.
