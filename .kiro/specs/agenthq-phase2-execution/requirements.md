# Requirements Document

## Introduction

AgentHQ MVP Phase 2 introduces autonomous task execution, building on Phase 1's validated foundation. Phase 1 provides project creation, Manager planning, task persistence with dependencies, and event recording. Phase 2 enables the execution orchestrator to identify ready tasks, dispatch them to specialist agents, run agent logic, interact with isolated project workspaces, capture execution results, and handle failures with retry logic.

The execution model uses a three-stage approach: claim transaction (reserve task), agent execution (outside transaction, writing to staging directory), and finalization transaction (promote files, persist results). This design isolates long-running LLM calls from database locks while maintaining execution integrity.

The first implementation milestone delivers one complete working path: Manager creates tasks → Orchestrator identifies eligible task → BackendAgent executes → Staging operations → Workspace promotion → Execution Result persisted. All other specialist agents remain as stubs until their respective phases.

Phase 2 assumes a single application process and single orchestrator instance. Multi-process orchestration with execution leases is deferred to a future phase. The synchronous HTTP execution model is suitable for MVP validation but production deployments should implement background worker orchestration to avoid HTTP request timeouts and enable concurrent project execution.

Phase 2 extends the Phase 1 task state machine by adding the `blocked → ready` transition to support the retry flow. The retry endpoint transitions a blocked task to ready, making it eligible for orchestrator dispatch while preserving existing state machine transitions.

Filesystem consistency: The three-stage execution model acknowledges that complete cross-resource atomicity between SQLite and the filesystem is not guaranteed. If finalization fails after file promotion, compensation logic attempts to revert promoted files, but filesystem errors during compensation may leave orphaned files. This trade-off is acceptable for Phase 2 simplicity, with startup recovery using promotion manifests for clean recovery.

Process lifecycle: Phase 2 assumes a single application process. The Flask development reloader creates a new process on code changes, which triggers startup recovery in the new process. Each process runs recovery exactly once during its initialization before accepting HTTP requests.

Phase 2 does not integrate Graphify, migrate to PostgreSQL, or implement all specialists simultaneously. It preserves the modular monolith architecture and keeps Hugging Face as the temporary development LLM provider.

Specification precedence: this requirements document is the acceptance contract. The design document must implement and remain consistent with these requirements. If a contradiction is discovered, these requirements take precedence until both files are corrected. Implementers SHALL NOT silently choose a weaker recovery, cancellation, timeout, or filesystem-boundary behaviour than the requirements specify.

---

## Glossary

- **Execution_Orchestrator**: The component that identifies eligible tasks, prevents duplicate execution, dispatches tasks to agents, captures results, and coordinates retry logic.
- **Specialist_Agent**: A concrete BaseAgent implementation (backend, frontend, designer, qa, utility) that receives a task and context, invokes the LLM, performs workspace operations via tools, and returns an AgentResult.
- **BackendAgent**: The first fully operational specialist agent implementation in Phase 2, assigned tasks with `assigned_role=backend`.
- **Project_Workspace**: An isolated directory at `workspace/<project-id>/` that contains all files and artifacts for a single project; all filesystem operations must remain within this boundary.
- **Staging_Directory**: A temporary execution-specific directory at `workspace/<project-id>/.staging/<execution-id>/` where agents write files during execution; files are promoted to workspace root upon successful finalization.
- **Workspace_Boundary**: The security constraint enforcing that no filesystem tool may read or write paths outside `workspace/<project-id>/` via path traversal, symlinks, or absolute paths.
- **FilesystemTool**: The tool layer abstraction providing `read_file()`, `write_file()`, `list_directory()`, and `file_exists()` operations with automatic workspace boundary enforcement.
- **Execution**: A database record capturing the start, end, status, agent output, artifacts, and errors for a single agent invocation on a task.
- **Task_Eligibility**: The condition where a task has `status=ready`, has no `in_progress` execution, and is assigned to a fully implemented specialist role (in Phase 2, only `backend`), making it available for dispatch.
- **Execution_Lock**: The mechanism preventing two orchestrator runs from dispatching the same task concurrently; implemented as a partial unique index on `Execution(task_id)` applying only when `status = 'in_progress'` using SQLite's indexed WHERE clause.
- **Execution_Retry**: The strategy for re-attempting a failed task execution after a configurable delay, respecting a maximum retry count.
- **Retry_Count**: The number of previous completed attempts for a task; stored in `Execution.retry_count` where 0=initial attempt, 1=first retry, 2=second retry.
- **Attempt_Number**: The sequential number of this execution attempt; calculated as `retry_count + 1` where 1=initial attempt, 2=first retry, 3=second retry.
- **Artifact**: A named output file produced by an agent execution (e.g., `api.py`, `schema.sql`, `design.png`) and tracked in the database with its workspace path.
- **Agent_Context**: A dictionary passed to `BaseAgent.run()` containing `project_id`, canonical `workspace_path` and `staging_path`, a staging-bound `filesystem_tool`, `llm_router`, execution deadline, and an execution-scoped cancellation token. Phase 1 Manager planning does not use this dictionary and does not require a cancellation token or execution deadline.
- **Synchronous_Execution**: The initial execution strategy where task dispatch and agent execution occur within the HTTP request-response cycle, blocking until the agent completes or times out.
- **Background_Worker**: A future execution strategy where task dispatch is triggered by a separate process or scheduled job, allowing long-running agent executions without blocking HTTP responses; not implemented in Phase 2.
- **Chain_of_Thought**: Internal LLM reasoning output that must never be persisted in the database or exposed to the UI; only validated structured output is stored.
- **Agent_Output**: The structured result returned by an agent in the `AgentResult.output` dictionary, containing only application-level keys (e.g., `files`, `summary`, `errors`) with primitive values.
- **Safe_Execution_Environment**: The collection of constraints limiting agent capabilities: workspace boundaries, staging directories, timeout limits, output size limits, and environment variable sanitization.
- **Command_Allowlist**: The explicit set of shell commands an agent may execute via a CommandTool, initially including `ls`, `cat`, `mkdir`, `cp`, `mv`, `rm`, and `git` with argument restrictions; not implemented in Phase 2 initial milestone.
- **Three_Stage_Execution**: The execution model consisting of: Stage A (claim transaction), Stage B (agent execution outside transaction), Stage C (finalization transaction).
- **Promotion_Manifest**: A durable execution-specific record, initially at `workspace/<project-id>/.staging/<execution-id>/promotion_manifest.json` and retained in a service-owned recovery location when needed. It contains `execution_id`, `project_id`, staged/destination paths, expected hashes, per-file promotion status, lifecycle status, and timestamps.

---

## Requirements

### Requirement 1: Project Workspace Initialization

**User Story:** As a developer, I want every project to have an isolated workspace directory, so that agent file operations cannot escape project boundaries or interfere with other projects.

#### Acceptance Criteria

1. WHEN a `Project` is created, THE System SHALL create a directory at `workspace/<project-id>/` before the project creation response is returned to the caller.
2. THE System SHALL enforce that `<project-id>` is a valid UUID4 string before creating the directory; IF the identifier is not a valid UUID4, THE System SHALL raise a `ValueError` and not create any directory.
3. IF the `workspace/<project-id>/` directory already exists at project creation time, THE System SHALL raise a `ConflictError` and not persist the `Project` record.
4. WHEN a `Project` is deleted, THE WorkspaceService SHALL validate workspace ownership, stage database cascade deletes in a caller-owned transaction, securely delete the canonical workspace before commit, and commit only after deletion succeeds. IF filesystem deletion fails, it SHALL rollback the database transaction. IF database commit fails after deletion, it SHALL raise and log an unrecoverable consistency error for operator repair; the System SHALL not claim cross-resource atomicity.
5. THE WorkspaceService SHALL expose `get_workspace_path(session: Session, project_id: str) -> Path`, returning the absolute path to `workspace/<project-id>/` without performing child filesystem operations.
6. IF `get_workspace_path()` is called with a `project_id` that does not match a persisted `Project` record, THE System SHALL raise a `NotFoundError`.
7. THE System SHALL create a `.staging/` subdirectory within `workspace/<project-id>/` during project initialization; this directory SHALL be used to hold execution-specific staging directories.

---

### Requirement 2: Filesystem Tool with Boundary Enforcement

**User Story:** As a developer, I want all filesystem operations to enforce workspace boundaries automatically, so that agents cannot read sensitive host files or write outside their project.

#### Acceptance Criteria

1. THE System SHALL define a `FilesystemTool` class in `app/tools/filesystem.py` with methods: `read_file(relative_path: str) -> str`, `write_file(relative_path: str, content: str) -> None`, `list_directory(relative_path: str) -> list[str]`, `file_exists(relative_path: str) -> bool`.
2. THE `FilesystemTool` constructor SHALL accept a `workspace_root: Path` parameter representing the absolute path to `workspace/<project-id>/` or `workspace/<project-id>/.staging/<execution-id>/`.
3. WHEN any `FilesystemTool` method receives a `relative_path` argument, THE tool SHALL: (1) resolve `workspace_root` to canonical absolute path, (2) construct `candidate_path = workspace_root / relative_path`, (3) reject the path if any existing component is a symlink (do not follow in-workspace or out-of-workspace symlinks), (4) resolve the non-symlink candidate to a canonical absolute path, (5) verify resolved `candidate_path` is equal to `workspace_root` OR is a child of `workspace_root` using `path.is_relative_to(workspace_root)` or equivalent safe comparison (NOT string prefix matching), (6) IF verification fails, raise `WorkspaceBoundaryError` with a message indicating the rejected path and not perform any filesystem operation.
4. THE `FilesystemTool` SHALL reject any `relative_path` containing `..` segments, absolute path prefixes (e.g., `/`, `C:\`), or `~` expansion; IF such a path is provided, THE tool SHALL raise a `WorkspaceBoundaryError` before attempting path resolution.
5. THE `FilesystemTool` SHALL reject every symlink in the candidate path, including a symlink whose target would remain inside `workspace_root`; it SHALL raise `WorkspaceBoundaryError` and SHALL NOT follow the symlink.
6. THE `FilesystemTool` SHALL defend against TOCTOU (time-of-check-time-of-use) symlink races by re-verifying path containment after opening file descriptors where possible.
7. WHEN `write_file()` is called with a `relative_path` whose parent directory does not exist, THE tool SHALL create all necessary parent directories within the workspace before writing the file.
8. WHEN `read_file()` is called with a `relative_path` that does not exist, THE tool SHALL raise a `FileNotFoundError` with a message indicating the file was not found within the workspace.
9. WHEN `list_directory()` is called with a `relative_path` that is not a directory or does not exist, THE tool SHALL raise a `NotADirectoryError` or `FileNotFoundError` respectively.
10. THE `FilesystemTool` SHALL NOT log the content of files read or written at any log level.
11. THE `FilesystemTool` SHALL provide a method `file_exists_at_destination(relative_path: str) -> bool` that checks if a file exists at the given path within the workspace boundary without opening or reading the file.
12. THE System SHALL define `WorkspaceOperations` as the only abstraction permitted to promote, compensate, or recover workspace files. It SHALL apply the same canonical containment, symlink rejection, descriptor revalidation, and no-replace semantics to staging sources and workspace destinations; agents and orchestrator code SHALL not bypass it with raw path or shutil operations.

---

### Requirement 3: Execution Model and Database Schema

**User Story:** As a developer, I want execution results to be persisted reliably, so that every agent invocation is traceable and execution history is preserved.

#### Acceptance Criteria

1. THE System SHALL define an `Execution` SQLAlchemy model in `app/models/execution.py` with fields: `id` (UUID string, primary key), `task_id` (foreign key to `tasks.id`, non-nullable), `project_id` (foreign key to `projects.id`, non-nullable), `agent_role` (string, non-nullable, constrained to `AgentRole` values), `status` (string, non-nullable, constrained to values: `in_progress`, `success`, `failure`, `timeout`), `started_at` (datetime, nullable), `completed_at` (datetime, nullable), `output` (text, nullable, stores JSON string), `error_message` (string, max 500 characters, nullable), `retry_count` (integer, non-nullable, default 0, represents number of previous completed attempts for this task), `created_at` (datetime, non-nullable).
2. THE `Execution` model SHALL have a relationship to `Task` such that deleting a `Task` cascades to delete all associated `Execution` records.
3. THE `Execution` model SHALL store agent output in the `output` column as a JSON string; the JSON SHALL contain only primitive values (strings, numbers, booleans, null) and arrays/objects of primitives with a maximum nesting depth of three levels.
4. THE System SHALL define an `Artifact` SQLAlchemy model in `app/models/artifact.py` with fields: `id` (UUID string, primary key), `execution_id` (foreign key to `executions.id`, non-nullable), `task_id` (foreign key to `tasks.id`, non-nullable), `project_id` (foreign key to `projects.id`, non-nullable), `name` (string, max 255 characters, non-nullable), `relative_path` (string, max 500 characters, non-nullable), `file_type` (string, max 50 characters, nullable), `size_bytes` (integer, nullable), `created_at` (datetime, non-nullable).
5. THE `Artifact` model SHALL have a relationship to `Execution` such that deleting an `Execution` cascades to delete all associated `Artifact` records.
6. THE `Artifact` model SHALL NOT store file content in the database; only the `relative_path` within the workspace is persisted.
7. THE System SHALL enforce duplicate execution prevention through exactly one SQLAlchemy model-declared partial unique index named `idx_execution_active` on `Execution(task_id)` with SQLite predicate `status = 'in_progress'`; no separate raw index-creation helper SHALL exist. All model/index declarations SHALL be imported before `Base.metadata.create_all(engine)`.
8. WHEN an `Execution` record transitions from `in_progress` to `success`, `failure`, or `timeout`, THE System SHALL set `completed_at` to the current UTC timestamp.

---

### Requirement 4: Task Eligibility and Three-Stage Dispatch Logic

**User Story:** As a developer, I want the orchestrator to identify which tasks are eligible for execution and manage the execution lifecycle using a three-stage model, so that work progresses automatically while isolating long-running operations from database locks.

#### Acceptance Criteria

1. THE Execution_Orchestrator SHALL define a method `identify_eligible_tasks(session: Session, project_id: str) -> list[Task]` that returns all tasks where `status=ready`, no `Execution` record exists with `status='in_progress'`, and `assigned_role` is in the `SUPPORTED_ROLES` set.
2. THE orchestrator SHALL expose a `SUPPORTED_ROLES` constant containing the set of fully implemented specialist roles; in Phase 2, `SUPPORTED_ROLES = {AgentRole.backend}`.
3. WHEN `identify_eligible_tasks()` is invoked, THE orchestrator SHALL filter tasks to only those assigned to fully implemented specialist roles; in Phase 2, only tasks with `assigned_role=backend` are eligible.
4. WHEN `identify_eligible_tasks()` is called, THE orchestrator SHALL query the database for tasks matching the eligibility criteria and return them ordered by explicit numeric priority rank (`high=3`, `medium=2`, `low=1`) descending, then by `created_at` ascending. String lexicographic ordering of the priority column SHALL NOT be used.
5. THE Execution_Orchestrator SHALL define `execute_ready_tasks(project_id: str) -> dict` and `dispatch_task(project_id: str, task_id: str) -> Execution`; it SHALL own fresh sessions for Stage A, Stage C, and failure persistence. `identify_eligible_tasks(session, project_id)` remains a read-only helper. Stage B SHALL have no open database transaction.

#### Stage A: Claim Transaction

6. WHEN `dispatch_task()` begins Stage A, it SHALL use a fresh transaction and authoritatively re-fetch the task/project. It SHALL verify task `ready`, supported role, all prerequisites `done`, and no in-progress execution before: (1) transition to `in_progress` through a non-committing TaskService operation, (2) create the execution with its retry count/timestamps, (3) record `execution.started`, and (4) commit and close the transaction.
7. IF the claim transaction commit fails due to a database constraint violation on the partial unique index (indicating another process claimed the task concurrently), THE orchestrator SHALL raise a `ConflictError` and not proceed to Stage B.
8. IF the claim transaction commit fails for any other reason, THE orchestrator SHALL rollback and raise the exception.

#### Stage B: Agent Execution (Outside Transaction)

9. WHEN Stage A completes successfully, THE orchestrator SHALL create a staging directory at `workspace/<project-id>/.staging/<execution-id>/`.
10. THE orchestrator SHALL construct an `Agent_Context` dictionary containing `project_id`, canonical workspace/staging paths, a staging-bound `FilesystemTool`, shared `llm_router`, execution deadline, and an execution-scoped cancellation token. It SHALL not expose ambient environment variables or database sessions.
11. THE orchestrator SHALL retrieve the agent from `agent_registry[task.assigned_role]` and invoke `agent.run(task, context)`.
12. THE agent execution in Stage B SHALL occur outside any database transaction, allowing long-running LLM calls without holding database locks.
13. WHEN the agent returns an `AgentResult`, THE orchestrator SHALL validate that `AgentResult.output` (if status is success) does not exceed 100,000 characters when serialized to JSON; IF the size limit is exceeded, THE orchestrator SHALL treat the execution as a failure and construct a failure `AgentResult` with error "Agent output exceeds maximum size limit".
14. The agent and router SHALL cooperatively check the cancellation token before and after network operations and before every filesystem write. On timeout the orchestrator SHALL signal cancellation and wait up to `CANCELLATION_GRACE_SECONDS` (default 5) for acknowledgement; until acknowledgement, it SHALL not finalize, delete staging, or permit retry. `Future.result(timeout=...)` alone SHALL NOT be used as cancellation. IF acknowledgement is not received within the grace period, the execution SHALL remain `in_progress` with staging/manifest retained for startup recovery. IF the agent raises an unhandled exception during `run()`, THE orchestrator SHALL construct a safe failure `AgentResult` without stack traces.

#### Stage C: Finalization Transaction

15. WHEN Stage B completes (agent returns result or raises exception), Stage C SHALL use no database transaction during filesystem promotion and SHALL use a new short database transaction only for final execution/artifact/task/event persistence. This avoids holding a database transaction during filesystem I/O while preserving one atomic database finalization.
16. IF the agent returned `AgentResult` with `status="success"`, THE orchestrator SHALL perform the following steps in order:

a. **Batch Validation Phase**: BEFORE promoting any files, THE orchestrator SHALL validate the entire batch by checking if any destination path in `AgentResult.output['files']` already exists in the workspace. IF any destination file exists, THE orchestrator SHALL reject the entire batch by: (1) skipping file promotion, (2) updating the `Execution` record to `status=failure` with error message "File collision: destination path already exists", (3) transitioning the task to `status=blocked`, (4) recording an `execution.failed` event, and (5) committing the transaction. No files shall be promoted when a collision is detected.

b. **File Promotion Phase**: ONLY IF no collisions were detected, THE orchestrator SHALL use the privileged boundary-validated workspace operation abstraction to promote each verified regular file without overwrite. The orchestrator SHALL maintain a durable promotion manifest tracking per-file hashes and promotion status.

c. **Artifact Creation Phase**: THE orchestrator SHALL iterate over `AgentResult.output['files']` and call `execution_service.create_artifact()` for each file.

d. **Execution Update Phase**: THE orchestrator SHALL update the `Execution` record to `status=success` and store `AgentResult.output` as JSON string in `Execution.output`.

e. **Task Transition Phase**: THE orchestrator SHALL transition the task to `status=review`.

f. **Event Recording Phase**: THE orchestrator SHALL record a `task.status_changed` event and an `execution.completed` event containing execution identifier, task identifier, project identifier, agent role, duration in milliseconds, and artifact count.

g. **Transaction Commit Phase**: THE orchestrator SHALL commit the transaction. Only after that commit succeeds SHALL it mark the Promotion_Manifest lifecycle status `completed` and then delete the staging directory and completed manifest. A manifest SHALL never be marked `completed` before successful database finalization.
17. IF the agent returned `AgentResult` with `status="failure"` or any unrecognized status value other than `"success"`, THE orchestrator SHALL: (1) update the `Execution` record to `status=failure` and store error message (from `AgentResult.error` or a message indicating unrecognized status) in `Execution.error_message` truncated to 500 characters if necessary, (2) transition the task to `status=blocked`, (3) record a `task.status_changed` event, (4) record an `execution.failed` event containing execution identifier, task identifier, and safe error summary, (5) commit the transaction.
18. WHEN database finalization commits successfully, THE orchestrator SHALL then mark the manifest `completed` and delete the staging directory and completed manifest. When compensation or database finalization is incomplete, it SHALL retain or relocate the durable manifest for startup recovery and SHALL NOT mark the manifest `completed`.
19. IF database finalization commit fails after files have been promoted, THE orchestrator SHALL retain a `database_pending` manifest, log an error with project/task/execution identifiers, and prevent automatic retry until recovery reconciles the manifest. It SHALL NOT treat logging alone as recovery and SHALL NOT mark the manifest `completed`.
20. THE orchestrator SHALL apply a per-task execution deadline (configurable via `EXECUTION_TIMEOUT_SECONDS`, default 180 seconds) to Stage B. It SHALL signal cooperative cancellation at the deadline and transition to timeout/finalization only after acknowledgement. If acknowledgement is missing, it SHALL retain the in-progress execution and staging/manifest for startup recovery; it SHALL not transition the task, finalize, clean up, or retry while writes may continue. The default accommodates cold-start latency; lower-latency deployments may reduce it.

21. THE integration test SHALL demonstrate that a backend-assigned task with zero prerequisites is automatically transitioned to `status=ready` by the normal task service dependency evaluation logic, and can be dispatched by the orchestrator without violating dependency invariants or requiring manual status manipulation.



22. THE System SHALL enforce that no pre-existing project file is ever overwritten or deleted by file promotion or compensation logic. All file collisions SHALL cause batch rejection before any promotion occurs.

23. WHEN file promotion begins (Stage C), THE orchestrator SHALL create a Promotion_Manifest containing execution/project identifiers, all staged and destination paths, expected hashes, lifecycle status, and per-file status. BEFORE promoting each file, THE orchestrator SHALL durably mark that file as `promoting`; AFTER verified promotion, it SHALL durably mark that file as `promoted`.

24. WHEN file promotion and database finalization both complete successfully, THE orchestrator SHALL update the Promotion_Manifest lifecycle status to `completed` only after the database commit has succeeded, then delete the completed manifest with the staging directory. A manifest SHALL never be marked `completed` before successful database finalization. Until then it SHALL retain the manifest in staging or in a service-owned recovery location.

25. WHEN file promotion fails or is interrupted, THE Promotion_Manifest SHALL remain durable with lifecycle status `promoting`, `compensation_failed`, or `database_pending` and a record of verified promoted files.

26. WHEN file promotion fails (e.g., due to filesystem error, insufficient permissions, or collision detection), THE orchestrator SHALL perform compensation in this exact sequence:

a. **Stop Promotion**: Immediately halt any further file promotion.

b. **Clean Promoted Files**: Delete only files marked `promoted` whose current hash matches the manifest expected hash; preserve and log any mismatch.

c. **Update Manifest**: Update Promotion_Manifest lifecycle status to `compensation_failed` if any cleanup fails, otherwise record each file as compensated.

d. **Open Fresh Transaction**: Open a new database transaction (not reusing the failed transaction).

e. **Record Failure**: Update the `Execution` record to `status=failure` with appropriate error message.

f. **Transition Task**: Transition the associated `Task` to `status=blocked`.

g. **Record Event**: Record an `execution.failed` event with safe error summary.

h. **Commit**: Commit the fresh transaction.

i. **Cleanup**: Delete the staging directory and manifest only after successful compensation and failure persistence; otherwise retain/relocate the manifest for recovery.

27. IF compensation cleanup (step b) fails for any file, THE orchestrator SHALL:
   - Log the specific file failure at `ERROR` level
   - Continue with remaining compensation steps
   - The Promotion_Manifest will remain for startup recovery cleanup

28. THE orchestrator SHALL NOT reuse or rollback a failed finalization transaction for recording failure state; it SHALL always open a fresh transaction for failure recording after cleanup.

---

### Requirement 5: BackendAgent Implementation

**User Story:** As a developer, I want the BackendAgent to be the first fully operational specialist, so that backend-assigned tasks can be executed with real LLM calls and staging directory operations.

#### Acceptance Criteria

1. THE System SHALL implement `BackendAgent` in `app/agents/backend.py` as a concrete subclass of `BaseAgent` with `name="Backend"` and `role=AgentRole.backend`.
2. THE `BackendAgent` constructor SHALL accept `llm_router: LLMRouter` and `model_config: ModelConfig` parameters and store them as instance attributes.
3. THE `BackendAgent.run()` method SHALL accept a `task: Task` and `context: dict` and return an `AgentResult`.
4. WHEN `BackendAgent.run()` is invoked, THE agent SHALL construct a prompt containing the task title, task description, and staging path, invoke `llm_router.complete(role="BACKEND", prompt=...)`, parse the raw response, validate it against a Pydantic schema defining structured output, and return an `AgentResult`.
5. THE `BackendAgent` prompt SHALL instruct the LLM to return only a JSON object with `summary` (string), `files` (array of `{relative_path, content, purpose, file_type}` objects), and `next_steps` (array of strings). `content` is input to staging-file creation only and SHALL NOT be persisted in `AgentResult.output`, `Execution.output`, events, logs, or UI. Markdown code fences are forbidden.
6. WHEN the LLM response is valid JSON matching the LLM-response Pydantic schema, THE agent SHALL write each `content` value to its `relative_path` in the staging directory using `context["filesystem_tool"].write_file()`. It SHALL return a separately validated persisted-output schema containing only sanitized `summary`, file metadata (`relative_path`, byte `size_bytes`, `file_type`, `purpose`), and `next_steps`.
7. THE agent SHALL write all files to the staging directory provided in `context['staging_path']`, NOT to the workspace root.
8. THE agent SHALL return `AgentResult` containing a `files` list in the output dictionary, where each file entry includes `{relative_path, size_bytes, file_type, purpose}`.
9. THE agent SHALL NOT persist any database records, SHALL NOT record events, and SHALL NOT transition task status; these responsibilities belong to the orchestrator.
10. IF the LLM response cannot be parsed as JSON or fails schema validation, THE agent SHALL return `AgentResult(status="failure", output={}, error="Invalid LLM response format")` without writing any files.
11. IF a filesystem operation raises a `WorkspaceBoundaryError`, THE agent SHALL return `AgentResult(status="failure", output={}, error="Workspace boundary violation")` immediately; the orchestrator will cleanup the staging directory during finalization.
12. THE `BackendAgent` SHALL NOT persist the raw LLM response or any chain-of-thought content in the `AgentResult`; only the validated structured output SHALL be included in `AgentResult.output`.
13. WHEN the LLM returns a response exceeding 100,000 characters, THE agent SHALL return `AgentResult(status="failure", output={}, error="LLM response exceeds maximum size limit")` without attempting to parse or persist the response.
14. THE System SHALL enforce a maximum file size of 10 MB (10,485,760 bytes) for any file written via `FilesystemTool.write_file()`; IF an agent attempts to write a file exceeding this limit, THE tool SHALL raise a `FileSizeLimitError` before writing the file.
15. THE BackendAgent MAY generate test files (e.g., `test_*.py`) as part of its output.
16. Generated test files SHALL be tracked as artifacts but SHALL NOT be executed in Phase 2.
17. THE System SHALL NOT report test results or test pass/fail status in Phase 2.
18. Command execution including test execution is explicitly OUT OF SCOPE for Phase 2.

---

### Requirement 6: Artifact Tracking

**User Story:** As a CEO, I want to see which files each agent execution created, so that I can review deliverables and trace artifacts back to their originating task.

#### Acceptance Criteria

1. THE System SHALL provide a `create_artifact()` function in `app/services/execution_service.py` accepting parameters: `session`, `execution_id`, `task_id`, `project_id`, `name`, `relative_path`, `file_type`, `size_bytes`.
2. WHEN the orchestrator processes a successful `AgentResult` during finalization (Stage C), THE orchestrator SHALL iterate over `AgentResult.output['files']` and call `create_artifact()` for each file before committing the finalization transaction.
3. THE System SHALL expose a GET endpoint at `/api/projects/<project_id>/tasks/<task_id>/artifacts` returning a list of all `Artifact` records associated with the task, ordered by `created_at` descending.
4. WHEN the CEO views the task detail page, THE UI SHALL render a section listing all artifacts with their `name`, `relative_path`, `file_type`, `size_bytes`, and `created_at` timestamp.
5. IF an artifact's `relative_path` does not correspond to an existing file in the workspace, THE UI SHALL display the artifact metadata with a visual indicator that the file is missing, but SHALL NOT remove the artifact record from the database.
6. THE System SHALL NOT implement artifact download functionality in Phase 2; artifact records are metadata-only for traceability and no download endpoint or UI control shall exist.

---

### Requirement 7: Execution Service

**User Story:** As a developer, I want a centralized service for execution persistence, so that orchestrator and agent code delegates all execution-related database writes.

#### Acceptance Criteria

1. THE System SHALL define an `ExecutionService` class in `app/services/execution_service.py` with methods: `create_execution()`, `update_execution_status()`, `get_execution()`, `list_executions()`, `create_artifact()`.
2. THE `create_execution()` method SHALL accept parameters: `session`, `task_id`, `project_id`, `agent_role`, `retry_count`, `started_at`, and return an `Execution` instance with `status=in_progress` and `created_at` set to the current UTC timestamp.
3. THE `update_execution_status()` method SHALL accept parameters: `session`, `execution_id`, `new_status`, `output` (optional), `error_message` (optional), and update the `Execution` record; IF `new_status IN ('success', 'failure', 'timeout')`, THE method SHALL set `completed_at` to the current UTC timestamp.
4. THE `get_execution()` method SHALL accept `session` and `execution_id` and return the `Execution` instance; IF the execution does not exist, THE method SHALL raise a `NotFoundError`.
5. THE `list_executions()` method SHALL accept `session` and exactly one scope argument, `task_id` or `project_id`, and return matching `Execution` records ordered by `created_at` descending.
6. THE `create_artifact()` method SHALL accept parameters: `session`, `execution_id`, `task_id`, `project_id`, `name`, `relative_path`, `file_type`, `size_bytes`, and persist an `Artifact` record.
7. THE `ExecutionService` SHALL NOT call `session.commit()`; all commits SHALL be managed by the orchestrator or route layer.

---

### Requirement 8: Orchestrator Entry Point

**User Story:** As a developer, I want a single orchestrator function that processes all eligible tasks for a project, so that task execution can be triggered from a route or future background worker.

#### Acceptance Criteria

1. THE System SHALL define an `ExecutionOrchestrator` class in `app/orchestration/orchestrator.py` with a method `execute_ready_tasks(project_id: str) -> dict`; the orchestrator owns its sessions through its injected session factory.
2. WHEN `execute_ready_tasks()` is invoked, THE orchestrator SHALL open a short read session for `identify_eligible_tasks()`, then call `dispatch_task(project_id, task_id)` for each candidate.
3. WHEN `execute_ready_tasks()` processes eligible tasks, THE orchestrator SHALL skip tasks assigned to unsupported roles (roles not in `SUPPORTED_ROLES`) without creating Execution records, changing task status, or recording events; these tasks remain at `status=ready` for future phases.
4. THE `execute_ready_tasks()` method SHALL return a dictionary containing: `tasks_dispatched` (integer count), `tasks_succeeded` (integer count), `tasks_failed` (integer count), `execution_ids` (list of execution identifiers created).
5. IF `dispatch_task()` raises a `ConflictError` for a task (indicating a concurrent execution exists), THE orchestrator SHALL skip that task, log a warning at `INFO` level, and continue processing remaining tasks.
6. IF `dispatch_task()` raises any other exception, THE orchestrator SHALL log the error at `ERROR` level, include the task identifier and project identifier in the log message, and continue processing remaining tasks rather than aborting the entire batch.
7. THE `execute_ready_tasks()` method SHALL rely on each Stage A/Stage C/failure transaction being committed independently, ensuring that one task's failure does not roll back another task's successful execution. Eligible tasks not reached before the request deadline SHALL remain `ready`. They SHALL NOT be dispatched automatically; a subsequent CEO/API `POST /api/projects/<project_id>/execute` is required.
8. THE System SHALL expose a POST endpoint at `/api/projects/<project_id>/execute` that validates the project exists, calls `orchestrator.execute_ready_tasks(project_id)`, and returns a JSON response containing the orchestrator result dictionary.
9. WHEN the `/api/projects/<project_id>/execute` endpoint is invoked and no tasks are eligible, THE endpoint SHALL return a 200 response with `tasks_dispatched=0` rather than an error.

---

### Requirement 9: Synchronous Execution Model

**User Story:** As a developer, I want the initial execution strategy to be synchronous, so that Phase 2 can be validated without introducing a background worker or job queue.

#### Acceptance Criteria

1. THE System SHALL execute agent tasks within the HTTP request-response cycle for the `/api/projects/<project_id>/execute` endpoint; the response SHALL NOT be returned until all eligible tasks complete or fail.
2. THE System SHALL enforce a per-task Stage B deadline via `EXECUTION_TIMEOUT_SECONDS` (default 180). For Phase 2 agent execution, the deadline and cancellation token SHALL be passed through Agent → LLMRouter → BaseLLMProvider → HTTP helper. `LLM_REQUEST_TIMEOUT_SECONDS` (default 60) is the single configured provider-request timeout. WHEN an execution deadline exists, the helper timeout SHALL be `min(LLM_REQUEST_TIMEOUT_SECONDS, remaining_execution_deadline)` seconds; a non-positive remaining deadline cancels before the HTTP request. WHEN no execution deadline exists (Phase 1 Manager planning and other ordinary `complete()` calls), the helper timeout SHALL be `LLM_REQUEST_TIMEOUT_SECONDS` and SHALL NOT require a cancellation token or deadline. A synchronous blocking request is not forcibly interrupted: timeout state/finalization occurs only after cancellation acknowledgement. If acknowledgement is missing within `CANCELLATION_GRACE_SECONDS` (default 5), the execution remains `in_progress` with staging retained for valid startup recovery.
3. THE System SHALL enforce `ORCHESTRATOR_TIMEOUT_SECONDS` (default 600) as a dispatch admission deadline. Work not begun remains `ready` until a subsequent CEO/API `POST /api/projects/<project_id>/execute`. The route returns 504 only after a timed-out running agent acknowledges cancellation; it SHALL not falsely report a still-writing worker as stopped.
4. THE System SHALL log the start and end of each task dispatch at `INFO` level, including: project identifier, task identifier, agent role, and elapsed time in milliseconds.
5. WHERE a future background worker is introduced, THE existing `execute_ready_tasks()` method SHALL be reusable without modification; only the trigger mechanism (HTTP endpoint vs. scheduled job) SHALL change.

---

### Requirement 10: Failure Handling and Retry Logic

**User Story:** As a developer, I want failed tasks to be retryable with a maximum attempt count, so that transient LLM errors do not permanently block a project.

#### Acceptance Criteria

1. `AppConfig.max_retry_count` SHALL be the single source of truth, defaulting to 2: maximum two retries after the initial attempt (three total attempts, with retry counts 0, 1, and 2).
2. WHEN a task execution completes with `status=failure`, THE task SHALL remain at `status=blocked` and be excluded from `identify_eligible_tasks()` results.
3. THE System SHALL expose a PATCH endpoint at `/api/projects/<project_id>/tasks/<task_id>/retry` that validates the task exists, verifies `status=blocked`, checks the most recent terminal execution has `retry_count < AppConfig.max_retry_count`, then uses a non-committing TaskService transition in one route-owned transaction to move it to `ready`. `task.retry_requested` SHALL be recorded through EventService inside that same service-owned transaction. The thin route SHALL NOT call EventService directly and SHALL NOT invoke the Phase 1 committing `TaskService.update_task_status()` inside a larger transaction.
4. IF a retry request is made for a task where the most recent execution has `retry_count >= AppConfig.max_retry_count`, THE endpoint SHALL return a 409 (Conflict) response with an error message indicating the retry limit has been reached.
5. IF a retry request is made for a task where `status != blocked`, THE endpoint SHALL return a 409 (Conflict) response with an error message indicating only blocked tasks may be retried.
6. WHEN a task is transitioned to `status=ready` via the retry endpoint, THE next invocation of `execute_ready_tasks()` SHALL identify the task as eligible, create a new `Execution` record with `retry_count` incremented, and dispatch the task normally.
7. THE `retry_count` value in the `execution.failed` event payload SHALL represent the number of previous attempts (0=initial attempt failed, 1=first retry failed, 2=second retry failed), so that event history reflects which attempt failed.

---

### Requirement 11: Security Constraints for Agent Execution

**User Story:** As a developer, I want agent execution to be constrained by security boundaries, so that autonomous LLM-driven code cannot compromise the host system.

#### Acceptance Criteria

1. THE System SHALL enforce that all `FilesystemTool` operations are bounded to `workspace/<project-id>/` or `workspace/<project-id>/.staging/<execution-id>/` as defined in Requirement 2.
2. THE System SHALL NOT provide agents with access to environment variables containing the substring `KEY`, `TOKEN`, `SECRET`, or `PASSWORD` (case-insensitive match); IF an agent requests environment configuration, THE `Agent_Context` SHALL include only safe variables explicitly allowlisted (e.g., `PROJECT_ID`, `WORKSPACE_PATH`).
3. THE System SHALL NOT persist API keys, LLM provider credentials, or raw LLM responses in the `Execution.output` field; only structured application output validated via Pydantic SHALL be stored.
4. THE System SHALL truncate `Execution.error_message` to 500 characters; IF an error message exceeds this length, THE service SHALL truncate it and append `... [truncated]` to indicate truncation.
5. THE System SHALL NOT expose Python exception stack traces in the `error_message` field; only safe, user-facing error descriptions SHALL be stored.
6. WHERE command execution tools are introduced in a future phase, THE System SHALL enforce an allowlist of permitted commands and reject any command not on the allowlist with a `PermissionError`.
7. THE System SHALL NOT execute shell commands in Phase 2 initial milestone; BackendAgent file operations SHALL use only the `FilesystemTool` methods.

---

### Requirement 12: Event Recording for Execution Lifecycle

**User Story:** As a CEO, I want execution lifecycle events recorded automatically, so that the activity feed reflects all agent work accurately.

#### Acceptance Criteria

1. THE System SHALL record the following events during execution orchestration: `execution.started`, `execution.completed`, `execution.failed`, `execution.timeout`, `task.retry_requested`.
2. WHEN the claim transaction (Stage A) creates an `Execution` with `status=in_progress`, THE orchestrator SHALL record an `execution.started` event with payload containing: `execution_id`, `task_id`, `project_id`, `agent_role`, `retry_count` (number of retries consumed for this task), `attempt_number` (retry_count + 1).
3. WHEN an `Execution` completes with `status=success` during finalization (Stage C), THE orchestrator SHALL record an `execution.completed` event with payload containing: `execution_id`, `task_id`, `project_id`, `agent_role`, `duration_ms` (milliseconds elapsed between `started_at` and `completed_at`), and `artifact_count`.
4. WHEN an `Execution` completes with `status=failure` during finalization (Stage C), THE orchestrator SHALL record an `execution.failed` event with payload containing: `execution_id`, `task_id`, `project_id`, `agent_role`, `retry_count` (number of retries consumed), `attempt_number` (retry_count + 1), `error_summary` (a safe 200-character summary of `error_message`).
5. WHEN an `Execution` exceeds the timeout limit, THE orchestrator SHALL record an `execution.timeout` event with payload containing: `execution_id`, `task_id`, `project_id`, `agent_role`, `timeout_seconds`.
6. WHEN the retry endpoint transitions a task to `status=ready`, THE TaskService (or an execution/retry service method used by the route) SHALL record a `task.retry_requested` event through EventService in the same caller-owned transaction, with payload containing: `task_id`, `project_id`, `retry_count` (number of retries consumed for the task before this retry). The route SHALL NOT call EventService directly.
7. THE System SHALL NOT include raw LLM output, API request/response bodies, or file content in event payloads.

---

### Requirement 13: Agent Registry Updates

**User Story:** As a developer, I want the agent registry to initialize BackendAgent with real LLM configuration, so that backend-assigned tasks can invoke the LLM Router.

#### Acceptance Criteria

1. THE `build_registry()` function in `app/agents/__init__.py` SHALL accept `llm_router: LLMRouter` and `app_config: AppConfig` parameters.
2. WHEN BackendAgent execution capability is enabled, the execution-capability factory SHALL instantiate `BackendAgent(llm_router, app_config.backend_model_config)` and register it at `AGENT_REGISTRY[AgentRole.backend]`; otherwise the existing backend stub remains registered.
3. THE `app_config.backend_model_config` SHALL be constructed from `AGENT_BACKEND_PROVIDER` and `AGENT_BACKEND_MODEL` only when BackendAgent execution capability is enabled or constructed. Missing values SHALL raise `ConfigurationError` at that capability boundary, not during ordinary Phase 1 application startup or tests that do not enable execution.
4. THE `build_registry()` function SHALL continue to register stub agents for `designer`, `frontend`, `qa`, and `utility` roles without requiring LLM configuration.
5. THE `AGENT_REGISTRY` SHALL remain a module-level dictionary accessible from orchestrator and service code; Phase 1 registry initialization remains compatible, and enabling execution replaces only the backend registration once the backend capability configuration is valid.

---

### Requirement 14: API Endpoints for Execution Management

**User Story:** As a CEO, I want API endpoints to trigger execution and view execution history, so that I can control when work happens and review results.

#### Acceptance Criteria

1. THE System SHALL expose `POST /api/projects/<project_id>/execute` accepting no request body, triggering orchestrator execution, and returning JSON with `tasks_dispatched`, `tasks_succeeded`, `tasks_failed`, `execution_ids`.
2. THE System SHALL expose `GET /api/projects/<project_id>/executions` returning all `Execution` records for the project ordered by `created_at` descending, each serialized with: `id`, `task_id`, `agent_role`, `status`, `started_at`, `completed_at`, `output` (parsed JSON), `error_message`, `retry_count`, `created_at`.
3. THE System SHALL expose `GET /api/projects/<project_id>/tasks/<task_id>/executions` returning all `Execution` records for a specific task ordered by `created_at` descending.
4. THE System SHALL expose `GET /api/executions/<execution_id>` returning a single `Execution` record with all fields; IF the execution does not exist, THE endpoint SHALL return a 404 response.
5. THE System SHALL expose `PATCH /api/projects/<project_id>/tasks/<task_id>/retry` accepting no request body, validating retry eligibility, transitioning the task to `ready`, and returning the updated task.
6. IF the project identifier in any endpoint does not match a persisted `Project`, THE endpoint SHALL return a 404 response.
7. IF the task identifier in any endpoint does not belong to the specified project, THE endpoint SHALL return a 404 response.

---

### Requirement 15: UI Updates for Execution Visibility

**User Story:** As a CEO, I want the project detail page to display execution history, so that I can see which tasks have run and review their outputs.

#### Acceptance Criteria

1. WHEN the CEO views the project detail page at `/projects/<project_id>`, THE page SHALL render an "Executions" section displaying the most recent 10 executions for the project, each showing: task title, agent role, status, started time, duration, and a link to view details.
2. WHEN the CEO views the task detail page at `/projects/<project_id>/tasks/<task_id>`, THE page SHALL render an "Execution History" section displaying all executions for that task ordered by `created_at` descending, each showing: status, started time, duration, retry count, and a summary from `output` if status is `success`.
3. WHEN an execution has `status=failure`, THE UI SHALL display the `error_message` in the execution row without exposing internal exception details.
4. WHEN an execution has `status=in_progress`, THE UI SHALL display a visual indicator (e.g., spinner icon) and the text "Running...".
5. WHERE a task has `status=blocked` and the most recent execution has `retry_count < AppConfig.max_retry_count`, THE task detail page SHALL render a "Retry Task" button that invokes `PATCH /api/projects/<project_id>/tasks/<task_id>/retry`.
6. THE project detail page SHALL display a "Run Tasks" button that invokes `POST /api/projects/<project_id>/execute` and displays a status message indicating how many tasks were dispatched.

---

### Requirement 16: Testing Requirements

**User Story:** As a developer, I want automated tests covering orchestrator logic, agent execution, and security boundaries, so that Phase 2 behavior is validated before declaring the milestone complete.

#### Acceptance Criteria

1. THE System SHALL include a test fixture `mock_llm_router` in `tests/conftest.py` that returns a stub `LLMRouter` implementation with a configurable `complete()` response.
2. THE System SHALL include a test fixture `test_workspace` that creates a temporary workspace directory for a test project and deletes it after the test completes.
3. THE System SHALL include unit tests in `tests/test_filesystem_tool.py` covering: successful read/write within workspace, boundary violation rejection for `..` paths, boundary violation rejection for absolute paths, symlink escape detection, parent directory creation, and TOCTOU defense verification.
4. THE System SHALL include unit tests in `tests/test_backend_agent.py` covering: successful LLM response parsing, file creation via FilesystemTool to staging directory, invalid LLM response handling, workspace boundary violation during file write, and proper AgentResult structure with files list.
5. THE System SHALL include unit tests in `tests/test_execution_orchestrator.py` covering: eligible task identification with role filtering, three-stage task dispatch success path, task dispatch failure path, duplicate execution prevention via partial unique index conflict, retry count increment, timeout handling, staging directory cleanup, and blocked → ready → in_progress transition chain.
6. THE System SHALL include integration tests in `tests/test_execution_integration.py` covering: end-to-end flow from `execute_ready_tasks()` through three-stage execution to artifact creation, with a real SQLite database session and mock LLM responses, and verification that files are promoted from staging to workspace root.
7. THE System SHALL include an integration test that creates a project with Manager planning, identifies a backend-assigned task with zero prerequisites through normal task creation service calls, and verifies `execute_ready_tasks()` successfully executes only that backend task without requiring other specialists or manually overriding task status. The test SHALL verify that tasks assigned to unsupported roles remain at `status=ready` and are not processed.
8. THE System SHALL include tests verifying that `Execution.output` does not contain raw LLM responses, API keys, or chain-of-thought content.
9. THE System SHALL include tests verifying that `error_message` truncation occurs when errors exceed 500 characters.
10. THE System SHALL include tests verifying that the `blocked → ready` transition is supported and that retried tasks naturally progress from `ready → in_progress` when dispatched by the orchestrator.
11. THE System SHALL include tests verifying that execution event payloads contain correct `retry_count` and `attempt_number` values, with the initial attempt recorded as `attempt_number=1, retry_count=0`.
12. THE System SHALL include tests verifying that partial file promotion failures trigger compensating cleanup, that pre-existing project files are never deleted by compensation, and that orphaned file detection during startup recovery logs appropriately.
13. Unit tests MAY use an in-memory SQLite database. Tests that exercise independent sessions, partial-index conflicts, or realistic contention SHALL use a temporary file-backed SQLite database so all connections observe the same database; every test database SHALL be isolated and removed after the test.

14. THE System SHALL include tests verifying file collision policy with measurable criteria:
    a. WHEN a destination file already exists, THE entire promotion batch SHALL be rejected before any file is promoted.
    b. NO pre-existing project files SHALL be overwritten or deleted.
    c. THE execution SHALL be recorded as failed with "File collision" error.
    d. THE task SHALL transition to `status=blocked`.

15. THE System SHALL include tests verifying multi-file batch collision behavior:
    a. WHEN multiple files in a batch have collisions, THE entire batch SHALL be rejected.
    b. Collision detection SHALL occur BEFORE any file promotion.
    c. ALL files in the staging directory SHALL remain unchanged.

16. THE System SHALL include tests simulating partial promotion failure:
    a. WHEN file promotion fails after some files have been promoted, compensation SHALL delete only those promoted files.
    b. Pre-existing project files SHALL be preserved.
    c. The Promotion_Manifest SHALL accurately reflect promoted files.
    d. Startup recovery SHALL cleanup using the manifest.

17. THE System SHALL include tests simulating process crash during promotion:
    a. WHEN a process crashes mid-promotion, startup recovery SHALL:
       - Load the durable manifest using `lifecycle_status`, per-file `promotion_status`, expected SHA-256, project ID, and execution ID
       - Read persisted `Execution.status` and associated `Task.status` before deciding any action
       - Preserve a successful execution with task `review` and persisted artifacts, complete its manifest, and delete only temporary manifest/staging data
       - Compensate only an in-progress execution with an interrupted promotion, and only exact manifest-owned regular files whose hashes match
       - Preserve and log any ownership, containment, symlink, or hash mismatch for manual inspection
       - Persist timeout/failure and task blocking only after reconciliation, using a valid fresh transaction

18. THE System SHALL include tests verifying compensation failure handling:
    a. WHEN file deletion during compensation fails, THE orchestrator SHALL:
       - Log error but continue with remaining compensation
       - Record execution failure
       - Leave Promotion_Manifest for startup recovery
    b. Startup recovery SHALL cleanup the failed compensation files.

19. THE System SHALL include tests verifying Promotion_Manifest lifecycle:
    a. Manifest creation at promotion start
    b. Manifest updates during file-by-file promotion
    c. Manifest deletion on successful completion
    d. Manifest persistence for crash recovery
    e. Manifest-based cleanup (not arbitrary orphan detection)
20. THE System SHALL include measurable cancellation tests verifying token checks before/after provider calls and before writes, acknowledged cancellation prevents post-cancellation writes/finalization/cleanup/retry, and missing acknowledgement retains the in-progress execution and staging directory for startup recovery.

---

### Requirement 17: Database Migration Strategy

**User Story:** As a developer, I want the database schema changes for Phase 2 to be applied automatically at startup, so that the application can initialize correctly in any environment.

#### Acceptance Criteria

1. THE System SHALL call `Base.metadata.create_all(engine)` during `create_app()` initialization after defining the `Execution` and `Artifact` models, ensuring all tables are created if they do not exist.
2. The model-declared `idx_execution_active` partial unique index SHALL be included in `Base.metadata.create_all(engine)` after all models are imported; no separate raw `CREATE UNIQUE INDEX` helper SHALL be used.
3. THE System SHALL verify that the `create_all()` call is idempotent and does not raise an error if tables already exist from a previous run.
4. WHERE the application is run against an existing Phase 1 database, THE `create_all()` call SHALL add only the new `executions` and `artifacts` tables without modifying or dropping existing `projects`, `tasks`, `task_dependencies`, `events`, or `messages` tables; existing `Project` and `Task` records SHALL remain accessible and functional without data migration or schema alteration.
5. THE System SHALL NOT use a migration framework (e.g., Alembic) in Phase 2; the initial schema, including model-declared indexes, is managed via `create_all()` only.
6. WHERE a future phase requires schema alterations (column additions, type changes, constraint modifications), THE project documentation SHALL note that Alembic will be introduced before such changes are made.

---

### Requirement 18: Configuration and Environment Variables

**User Story:** As a developer, I want all execution-related configuration to be loaded from environment variables, so that timeouts, retry limits, and workspace paths are configurable per deployment.

#### Acceptance Criteria

1. THE System SHALL read the following environment variables via `AppConfig`:
   - `WORKSPACE_ROOT`: absolute path to the workspace base directory (default: `./workspace`)
   - `EXECUTION_TIMEOUT_SECONDS`: per-task timeout in seconds for Stage B agent execution (default: 180)
   - `ORCHESTRATOR_TIMEOUT_SECONDS`: total orchestrator timeout in seconds (default: 600)
   - `MAX_RETRY_COUNT`: maximum retry attempts per task (default: 2)
   - `LLM_REQUEST_TIMEOUT_SECONDS`: configured timeout in seconds for one provider HTTP request (default: 60, matching the Phase 1 helper). WHEN an execution deadline exists, effective timeout is `min(configured value, remaining execution deadline)`. WHEN no deadline exists, effective timeout is the configured value.
   - `CANCELLATION_GRACE_SECONDS`: maximum seconds to wait for cooperative cancellation acknowledgement after the Stage B deadline (default: 5)
   - `AGENT_BACKEND_PROVIDER`: LLM provider name when BackendAgent execution is enabled
   - `AGENT_BACKEND_MODEL`: LLM model identifier when BackendAgent execution is enabled
2. THE `AppConfig` class SHALL validate that `WORKSPACE_ROOT` is an absolute path; IF a relative path is provided, THE config loader SHALL resolve it to an absolute path relative to the application root.
3. THE `AppConfig` class SHALL validate that `EXECUTION_TIMEOUT_SECONDS`, `ORCHESTRATOR_TIMEOUT_SECONDS`, `LLM_REQUEST_TIMEOUT_SECONDS`, and `CANCELLATION_GRACE_SECONDS` are positive integers greater than zero; IF invalid, THE config loader SHALL raise a `ConfigurationError`.
4. THE `AppConfig` class SHALL validate that `MAX_RETRY_COUNT` is a non-negative integer; IF invalid, THE config loader SHALL raise a `ConfigurationError`.
5. THE `.env.example` file SHALL list all Phase 2 environment variables with placeholder values and brief descriptions.
6. THE timeout configuration values SHALL be configurable to accommodate different deployment environments including cold start latency, network conditions, and LLM provider response times.

---

### Requirement 19: Logging and Observability

**User Story:** As a developer, I want execution orchestration to be logged at appropriate levels, so that debugging failures and tracing execution flow is straightforward.

#### Acceptance Criteria

1. THE Execution_Orchestrator SHALL log the following at `INFO` level: orchestrator start with project identifier, each task dispatch with task identifier and agent role, completion of each stage (claim, execution, finalization) with duration, each task completion with status and total duration, orchestrator end with summary counts.
2. THE Execution_Orchestrator SHALL log the following at `WARNING` level: duplicate execution conflict (Stage A claim failure), retry count approaching limit, staging directory deletion failure, finalization transaction failure after file promotion.
3. THE Execution_Orchestrator SHALL log the following at `ERROR` level: agent execution failure with task identifier and safe error summary, database constraint violation during execution creation, unexpected exceptions during dispatch, unrecoverable finalization errors.
4. THE FilesystemTool SHALL log boundary violations at `WARNING` level, including the rejected path and workspace root.
5. THE System SHALL NOT log file content, raw LLM responses, API keys, or environment variables containing sensitive substrings.
6. THE System SHALL use Python's standard `logging` module with logger names following the module hierarchy (e.g., `agenthq.orchestration.orchestrator`, `agenthq.tools.filesystem`).

---

### Requirement 20: Completion Criteria and Milestone Definition

**User Story:** As a developer, I want the Phase 2 milestone definition to be explicit, so that completion is objectively verifiable.

#### Acceptance Criteria

1. THE Phase 2 milestone SHALL be considered complete when the following conditions are met:
   - All 21 requirements in this document have passing tests.
   - A manual end-to-end verification succeeds: create project → trigger planning → verify backend task exists with `status=ready` → call `/api/projects/<id>/execute` → verify execution record created with `status=in_progress` during Stage A → verify staging directory created during Stage B → verify files promoted to workspace root during Stage C → verify task transitions to `review` → verify artifacts recorded in database → verify events recorded → verify staging directory deleted.
   - All Phase 1 tests continue to pass without modification.
   - The `BackendAgent` produces at least one file in the workspace for a sample backend task, demonstrating successful three-stage execution.
   - Code coverage for new modules (`orchestration/`, `tools/`, updated `agents/backend.py`) exceeds 80%.
2. THE System SHALL provide a test script `tests/manual_phase2_verification.py` that executes the end-to-end verification path using a real database, mock LLM responses, and verifies all expected state transitions including staging directory creation and cleanup.
3. THE completion criteria SHALL NOT require all specialist agents to be implemented; `designer`, `frontend`, `qa`, and `utility` SHALL remain as stubs.
4. THE completion criteria SHALL NOT require Graphify integration, PostgreSQL migration, or background worker implementation.
5. THE completion criteria SHALL NOT require a deployed environment; local execution against SQLite is sufficient.

---

### Requirement 21: Startup Recovery and Initialization

**User Story:** As a developer, I want the application to recover gracefully from crashes or restarts, so that stale execution states do not prevent future task processing.

#### Acceptance Criteria

1. Phase 2 SHALL run with one serving process and one orchestrator instance. Multi-process execution leases are deferred.
2. `startup_recovery()` SHALL run exactly once in the actual serving process before it accepts requests. It SHALL acquire an exclusive startup lock; in Werkzeug debug reload, `WERKZEUG_RUN_MAIN` identifies the serving child and the reloader parent SHALL not run recovery. Production SHALL use one worker and a handoff that stops the prior worker before the lock is acquired. Tests SHALL explicitly opt out through `PHASE2_STARTUP_RECOVERY_ENABLED=False` or use isolated resources.
3. Recovery SHALL first identify persisted `Execution` rows with `status='in_progress'`; it SHALL not alter them merely because a manifest is non-completed.
4. Recovery SHALL next discover and load every durable manifest in service-owned locations (`.staging/` and `.recovery/` for all projects). It SHALL NOT limit initial discovery to executions already identified as `in_progress`. For each loaded manifest it SHALL look up persisted Execution, Task, and Artifact records and validate project/execution ownership, canonical containment, symlink rejection, and per-file SHA-256 before any filesystem action.
5. IF persisted execution status is `success`, associated task status is `review`, and the required artifacts are persisted, recovery SHALL never compensate promoted files. It SHALL mark/retain the manifest as completed as appropriate and remove only temporary staging/recovery data.
6. IF persisted execution status is `in_progress` and manifest evidence shows interrupted promotion, recovery SHALL compensate only manifest-owned files with `promotion_status='promoted'` whose current regular-file hashes equal their expected SHA-256 values. A hash, symlink, containment, or ownership mismatch SHALL preserve the file and log an error for manual inspection.
7. IF lifecycle status is `database_pending`, recovery SHALL use persisted execution/task state as authoritative: for `success` plus `review` plus artifacts, it SHALL finalize the manifest without compensation; otherwise it SHALL perform the eligible interrupted-execution compensation of criterion 6, then persist `timeout` and task `blocked` in a fresh transaction. It SHALL never log and abandon the manifest.
8. Only after manifest reconciliation, recovery SHALL persist timeout/error/event and task blocking for every remaining in-progress execution using valid fresh transactions. It SHALL log each recovered execution at WARNING level.
9. Only after manifest reconciliation and terminal-state persistence, recovery SHALL delete validated abandoned staging directories. It SHALL not delete a directory or manifest before reconciliation; deletion failures are logged and recovery continues.
10. Recovery SHALL never scan or delete arbitrary workspace files; every automatic deletion requires verified manifest ownership and matching hash.
11. A process-local once-only guard and the exclusive startup lock SHALL prevent repeated/overlapping recovery. A recovery database error SHALL be logged and re-raised, preventing startup.
12. Recovery completion SHALL precede route serving. The design and tests SHALL exercise the exact order: identify in-progress executions, reconcile authoritative manifests, preserve successful executions, compensate eligible interrupted work, persist terminal recovery state, then clean abandoned staging data.

---
