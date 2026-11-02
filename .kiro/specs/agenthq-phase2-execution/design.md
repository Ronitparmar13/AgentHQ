# AgentHQ Phase 2 — Autonomous Task Execution Design

## 1. Purpose and scope

Phase 2 adds one real execution path to the existing Flask modular monolith:

```text
Manager plan → ready backend task → claim → BackendAgent → staging → promotion → review
```

Only `backend` is executable in this phase. `designer`, `frontend`, `qa`, and `utility` remain registered stubs and are left `ready` without executions or events. The design preserves SQLite, SQLAlchemy, Flask, Pydantic, and the provider-agnostic `LLMRouter`. It adds neither a queue nor a worker framework.

Execution is deliberately synchronous for MVP validation. It is not a production throughput architecture: one serving process, one orchestrator invocation at a time, no command execution, no test execution, no Graphify, and no container isolation.

Specification precedence: `.kiro/specs/agenthq-phase2-execution/requirements.md` is the acceptance contract. This design must implement and remain consistent with those requirements. If a contradiction is discovered, the requirements take precedence until both files are corrected. Implementers must not silently choose weaker recovery, cancellation, timeout, or filesystem-boundary behaviour.

## 2. Phase 1 compatibility

### 2.1 Authoritative current task lifecycle

The implementation in `app/constants.py` is authoritative:

```text
backlog → ready → in_progress → review → done
                         └────→ blocked
review → rework → in_progress | done
blocked → in_progress                 (Phase 1 current behavior)
```

Phase 2 makes one **additive** change: `blocked → ready`. It does not remove `blocked → in_progress`; the public retry flow uses `blocked → ready`, then the orchestrator claims `ready → in_progress`. This retains compatibility with any existing Phase 1 caller using `blocked → in_progress` while giving retry a dependency-compatible, observable path.

Regression tests must cover all existing transitions plus `blocked → ready → in_progress`; zero-prerequisite creation through `TaskService.create_task()` must still produce `ready`, and a blocked task must not become eligible until retried.

`TaskService.update_task_status()` currently commits and rolls back internally. That public method remains a route-level convenience only. Phase 2 adds transaction-aware, noncommitting service methods (or an explicit `commit=False` equivalent) for orchestrator use; they validate transitions, flush, and record the ordinary `task.status_changed` event but never commit or rollback. `ProjectService` has the same current commit-owning pattern and is not used inside execution transactions. `EventService.record()` already flushes but does not commit and is safe inside the caller-owned transaction.

## 3. Components and ownership

| Component | Responsibility | Transaction owner |
|---|---|---|
| `WorkspaceService` | project workspace lifecycle and canonical workspace lookup | caller |
| `FilesystemTool` | agent staging read/write/list/existence operations | none |
| `WorkspaceOperations` | privileged promotion, compensation, manifests, recovery cleanup | none |
| `ExecutionService` | execution/artifact persistence helpers; no commit | caller |
| `ExecutionOrchestrator` | claim, agent dispatch, finalization, result counts | opens a fresh session per stage |
| `BackendAgent` | validated generation and staging writes only | never receives a session |
| routes | request validation and HTTP mapping | no long-lived transaction |

The orchestrator is constructed with `session_factory`, `agent_registry`, `WorkspaceService`, `WorkspaceOperations`, `ExecutionService`, and `AppConfig`. Routes call orchestration/services only; they never call `EventService` directly. `TaskService`, `ProjectService`, and `ExecutionService` expose explicit noncommitting operations for caller-owned transactions, while their existing Phase 1 commit-owning methods remain compatibility wrappers.

```python
class ExecutionOrchestrator:
    def execute_ready_tasks(self, project_id: str) -> dict[str, object]: ...
    def identify_eligible_tasks(self, session: Session, project_id: str) -> list[Task]: ...
    def dispatch_task(self, task_id: str, project_id: str) -> Execution: ...
```

`execute_ready_tasks()` opens a short read session to find candidates and calls `dispatch_task()` by identifier. `dispatch_task()` never accepts a caller-owned request session; it opens and closes a fresh session for each database stage. This prevents a request session from accidentally retaining a transaction across the LLM call.

## 4. Workspace lifecycle

### 4.1 WorkspaceService

`WorkspaceService(workspace_root: Path, session_factory)` owns only paths beneath the configured absolute workspace root.

```python
def get_workspace_path(session: Session, project_id: str) -> Path: ...
def create_for_project(session: Session, title: str, description: str) -> Project: ...
def delete_for_project(session: Session, project_id: str) -> None: ...
```

`get_workspace_path()` validates UUID4 and verifies the persisted project record, then returns the canonical absolute `WORKSPACE_ROOT / project_id` without creating or inspecting a child path. Invalid UUID4 raises `ValueError`; an absent project raises `NotFoundError`.

### 4.2 Creation coordination

`ProjectService.create_project()` currently creates, records, and commits a project itself. Phase 2 refactors its internal logic into a noncommitting creation primitive used by `WorkspaceService`; the current public method can remain a wrapper for Phase 1 callers.

Creation sequence:

1. Validate request data and generated project UUID4 before filesystem mutation.
2. Begin a short database transaction, add/flush the project and `project.created` event, but do not commit.
3. Create exactly `workspace/<project-id>/` and `workspace/<project-id>/.staging/` with restrictive permissions. Existing project directory is a `ConflictError`; no project transaction is committed.
4. Commit the database transaction.
5. If filesystem creation fails, roll back the transaction. If database commit fails after directories were created, securely remove only those just-created, empty/known project directories, then re-raise. A cleanup failure is logged and raises an error; it is never silently ignored.

### 4.3 Deletion coordination

Project deletion is not presently implemented and therefore is introduced only with a dedicated service/route in the implementing phase. Its contract is: validate workspace ownership; stage database cascade deletes in a caller-owned transaction; securely remove the canonical workspace before commit; and commit only after removal succeeds. Filesystem failure rolls back the transaction. A post-deletion database-commit failure is an explicitly logged, unrecoverable consistency error for operator repair; the design does not claim cross-resource atomicity.

## 5. Filesystem security and privileged operations

### 5.1 FilesystemTool

`FilesystemTool` is bound either to a project root or one execution staging root. For every operation it:

1. rejects absolute paths, `~`, and any `..` path component before resolution;
2. resolves the root once to a canonical absolute directory;
3. resolves candidate/parent paths and verifies `candidate == root` or `candidate.is_relative_to(root)`—never string-prefix matching;
4. rejects symlinks in every existing component and rejects a resolved target outside the root;
5. uses descriptor-relative opening with `O_NOFOLLOW` where supported, then verifies the opened descriptor still resolves beneath the bound root; unsupported platforms fail closed for writes rather than silently weakening the boundary;
6. enforces UTF-8 file content and the 10 MiB byte limit before writing.

It never logs file content. `file_exists_at_destination()` performs canonical existence checking only; it does not open/read content.

### 5.2 WorkspaceOperations

Promotion and recovery must not bypass the boundary layer. `WorkspaceOperations` is the sole privileged abstraction for these operations. It accepts a project root, staging root, and a validated manifest; it applies the same canonical containment, symlink rejection, descriptor-relative access, and no-follow checks to **both** source and destination. No implementation may call raw `Path` or `shutil` operations on agent-controlled manifest paths.

Promotion workflow:

1. Revalidate every declared staged file, require a regular file, calculate its SHA-256 and byte size, and reject duplicate destination paths.
2. Canonically validate every destination and batch-check that none exists. A collision rejects the whole batch before any promotion.
3. Durably write/fsync the manifest before promotion. For each file, record `promoting`, fsync; create destination with no-replace semantics (`openat`/`O_CREAT|O_EXCL` or platform-equivalent); copy/link only from a verified staging descriptor; fsync file and parent; record `promoted` with the verified destination hash and fsync manifest. Do not mark the manifest `completed` in this step.
4. Persist artifacts, execution success, task `review`, and corresponding events in one short database transaction, then commit. Only after that commit succeeds, mark the durable manifest `completed` and fsync it. Then remove staging content and the completed manifest. If the database commit fails, retain `database_pending` (relocate the manifest if staging must not be the sole copy) and do not mark the manifest `completed`.

No pre-existing workspace file is overwritten or deleted. If any operation fails, promotion stops. Compensation deletes only a destination recorded as `promoted` whose current regular-file hash equals that entry’s expected hash; any mismatch is preserved and logged for manual review. The manifest remains durable whenever compensation is incomplete or a database commit has not succeeded.

## 6. Durable promotion manifest

The manifest lives at `workspace/<project-id>/.staging/<execution-id>/promotion_manifest.json` while staging exists. If it must survive staging cleanup, it is atomically copied/renamed to `workspace/<project-id>/.recovery/<execution-id>.json`, a private service-owned directory created with the workspace. This avoids the contradiction of deleting a staging directory while expecting its manifest to survive.

```json
{
  "version": 1,
  "execution_id": "uuid",
  "project_id": "uuid",
  "lifecycle_status": "prepared|promoting|completed|compensation_failed|database_pending",
  "files": [{
    "staged_path": "relative/path",
    "destination_path": "relative/path",
    "expected_sha256": "hex",
    "size_bytes": 123,
    "promotion_status": "prepared|promoting|promoted|compensated"
  }],
  "created_at": "UTC ISO-8601",
  "updated_at": "UTC ISO-8601"
}
```

All manifest paths are relative, independently validated, and never trusted merely because they appear in JSON.

## 7. Data contracts

### 7.1 LLM response schema — ephemeral only

Pydantic validates a JSON-only response before any write:

```python
class GeneratedFile(BaseModel):
    relative_path: str
    content: str
    purpose: str
    file_type: str

class BackendLLMResponse(BaseModel):
    summary: str
    files: list[GeneratedFile]
    next_steps: list[str]
```

The raw response is capped at 100,000 UTF-8 characters before parsing. File `content` is capped at 10 MiB UTF-8 bytes; paths are revalidated by `FilesystemTool`. Schema validation, duplicate paths, or any output whose normalized persisted form exceeds 100,000 serialized characters is failure. Raw response and `content` are discarded after staging writes.

### 7.2 Persisted AgentResult output schema

```python
class PersistedFileMetadata(BaseModel):
    relative_path: str
    size_bytes: int
    file_type: str
    purpose: str

class PersistedExecutionOutput(BaseModel):
    summary: str
    files: list[PersistedFileMetadata]
    next_steps: list[str]
```

Only this schema is serialised to `Execution.output`. It permits primitives/containers no deeper than three levels and expressly excludes raw provider responses, source contents, prompts, chain-of-thought, credentials, API request/response bodies, and test results. The agent returns `AgentResult(status="success", output=persisted_output)`, never writes database records/events/statuses, and reports malformed output as the safe failure `Invalid LLM response format`.

## 8. Models and services

`Execution` has UUID primary key; non-null task/project FKs; `agent_role` constrained to `AgentRole` values; status constrained to `in_progress|success|failure|timeout`; non-negative `retry_count`; nullable UTC start/completion timestamps; output text; and a 500-character error field. Its `Task` relationship cascades on task deletion. `completed_at` is set on every terminal update.

`Artifact` has UUID primary key, non-null `execution_id`, `task_id`, and `project_id` FKs, all indexed; `execution_id` cascades on execution deletion; metadata-only relative path/name/type/size; and UTC creation timestamp. Artifact content is never stored.

There is one duplicate-execution mechanism: model-declared SQLAlchemy index `idx_execution_active` with `unique=True` and SQLite predicate `status = 'in_progress'`. Models must be imported before `Base.metadata.create_all(engine)`; no second raw `CREATE INDEX` helper is permitted. A test inspects SQLite metadata and proves an independent-session `IntegrityError`.

`ExecutionService` has `create_execution`, `update_execution_status`, `get_execution`, `list_executions`, and `create_artifact`; `list_executions` accepts exactly one of `task_id` or `project_id`. Each takes a supplied session, flushes, validates schemas/statuses/error truncation, and never commits/rolls back.

`AppConfig.max_retry_count` is the sole retry-limit value. Existing Phase 1 startup continues to require only its present manager configuration. `AGENT_BACKEND_PROVIDER` and `AGENT_BACKEND_MODEL` are validated only by an execution-capability factory when BackendAgent execution is enabled/constructed, preserving Phase 1 app/test startup.

## 9. Three-stage orchestration

`SUPPORTED_ROLES = {AgentRole.backend}`. Eligibility lists `ready` tasks for the project with supported role and no active execution, ordered by explicit SQL priority rank `high=3`, `medium=2`, `low=1`, then oldest first. It is advisory only; Stage A is authoritative.

### Stage A — claim transaction

In a fresh session and short transaction, re-fetch by task/project ID and verify: project exists; task is `ready`; assigned role is supported; every prerequisite is `done`; and no `in_progress` execution exists. Calculate retry count from completed terminal executions. Transition task with the noncommitting service method to `in_progress`; create the execution with `started_at`; record `execution.started`; commit. The partial unique-index conflict becomes `ConflictError`, rolling back task/event/execution together. No staging or LLM operation occurs until commit succeeds.

### Stage B — cancellable agent execution

Create execution staging only after Stage A commit. The context contains project/workspace/staging canonical paths, a staging-bound `FilesystemTool`, an execution-scoped cancellation token, and the shared LLM router—never ambient environment variables. It supplies only allowlisted values (`PROJECT_ID`, `WORKSPACE_PATH`, `STAGING_PATH`).

The router and `BackendAgent.run()` must cooperatively check cancellation before and after network work and before every filesystem write. For execution requests, the agent passes the execution deadline and cancellation token through `LLMRouter` and the provider to the shared HTTP helper. `LLM_REQUEST_TIMEOUT_SECONDS` (default 60) is the configured provider-request timeout. When an execution deadline exists, the effective HTTP timeout SHALL be `min(LLM_REQUEST_TIMEOUT_SECONDS, remaining_execution_deadline)`; a non-positive remaining deadline cancels before the request. When no execution deadline exists, including Phase 1 Manager planning and ordinary `complete()` calls, the helper SHALL use `LLM_REQUEST_TIMEOUT_SECONDS` directly and SHALL NOT require a deadline or cancellation token. Cancellation of an in-flight synchronous HTTP request remains cooperative, not forcible.

At `EXECUTION_TIMEOUT_SECONDS` (default 180), orchestration signals cancellation and waits for an acknowledged terminal return. A synchronous in-flight `httpx.post()` is not forcibly interrupted by that token; after it returns, provider/agent code observes cancellation and must not write. If acknowledgement is not received within `CANCELLATION_GRACE_SECONDS` (default 5 seconds), orchestration does **not** finalize, clean staging, or permit retry; the execution remains in progress for valid startup recovery. `Future.result(timeout=...)` alone is prohibited because it leaves its worker running. Tests must prove acknowledged cancellation prevents subsequent writes and that missing acknowledgement retains execution/staging without finalization.

Stage B holds no SQLAlchemy transaction/session. Agent exception, validation failure, or acknowledged cancellation is converted to a safe failure/timeout result.

### Stage C — finalization transaction

For success, perform secure promotion while retaining the recovery manifest, then open a fresh short session and re-fetch the execution/task. Create artifacts from verified manifest metadata; persist the sanitized output; mark execution success/completion time; transition task `in_progress → review`; record status and completion events; commit. Only then remove staging and completed manifest.

For failure/timeout, open a fresh session, re-fetch, set terminal status/completion/error, transition task `in_progress → blocked`, record status plus failure/timeout event, commit, then clean staging. Promotion failures first retain/relocate the manifest and attempt hash-verified compensation; failure state is recorded in a **fresh** session after any failed finalization transaction. A post-promotion database failure leaves a `database_pending` manifest and blocks automatic retry until startup recovery reconciles it; it is never reduced to a log-only condition.

The per-request `ORCHESTRATOR_TIMEOUT_SECONDS` default 600 is an admission boundary, not permission to abandon running work. Candidates not started remain `ready` for the next synchronous call. The route returns 504 only after it has obtained cancellation acknowledgement; otherwise it returns a safe conflict/availability response indicating an active execution remains. Synchronous HTTP ties request capacity to LLM latency; background triggering is deferred.

## 10. Recovery and application startup

Startup recovery order is fixed:

1. Acquire the exclusive startup lock, then identify persisted `in_progress` executions. Do not change an execution merely because its manifest is non-completed.
2. Discover and load every durable manifest in service-owned `.staging` and `.recovery` locations across all projects, not only manifests associated with the executions identified in step 1. Validate each manifest, then consult its persisted Execution, Task, and Artifact records. Verify project/execution ownership, canonical containment, regular-file status, symlink rejection, and SHA-256 before any filesystem action.
3. For `Execution.success` with `Task.review` and persisted artifacts, never compensate. Mark the manifest complete as needed and delete only temporary staging/recovery data.
4. For `Execution.in_progress` plus an interrupted-promotion manifest, compensate only entries marked `promoted` whose destination hashes match the manifest. Preserve and error-log every mismatch, symlink, or ownership failure.
5. For `database_pending`, database state is authoritative: success/review/artifacts completes the manifest without compensation; every other state uses step 4, then persists timeout and task blocked through a fresh transaction. It is never merely logged and abandoned.
6. Persist timeout/error/event and task blocked for remaining recovered in-progress executions in fresh valid transactions.
7. Only then remove validated abandoned staging directories. Never scan or delete arbitrary workspace files.

`create_app()` creates engine/tables/index, builds services, establishes serving-process ownership, runs recovery, then registers/serves routes. `PHASE2_STARTUP_RECOVERY_ENABLED` defaults true only when execution is enabled. A process-local guard and startup lock prevent repeated recovery. In Werkzeug debug reload, recovery runs only when `WERKZEUG_RUN_MAIN == "true"`; the parent does no recovery. The supported development strategy is `use_reloader=False` whenever an execution can be active; the reloader-child path is allowed only after the old serving process has stopped and the lock is acquired. Production uses one worker and a handoff that terminates the old worker before the new one acquires the lock. Tests set `PHASE2_STARTUP_RECOVERY_ENABLED=False` unless exercising recovery with isolated resources. Multiple workers/processes are unsupported until leases are added.

## 11. Retry, events, APIs, and UI

`AppConfig.max_retry_count` is the sole retry-limit source and defaults to 2: retry counts are 0, 1, 2 and attempts are 1, 2, 3. Retry validates project/task ownership, blocked status, latest terminal execution, and `retry_count < AppConfig.max_retry_count`; otherwise it returns 409. It uses the noncommitting task transition in a route-owned short transaction to move `blocked → ready`, records `task.retry_requested`, and commits. It does not execute work itself.

Event payloads contain no raw output/content. Required fields are:

| Event | Payload |
|---|---|
| `execution.started` | `execution_id`, `task_id`, `project_id`, `agent_role`, `retry_count`, `attempt_number` |
| `execution.completed` | `execution_id`, `task_id`, `project_id`, `agent_role`, `duration_ms`, `artifact_count` |
| `execution.failed` | `execution_id`, `task_id`, `project_id`, `agent_role`, `retry_count`, `attempt_number`, safe 200-char `error_summary` |
| `execution.timeout` | `execution_id`, `task_id`, `project_id`, `agent_role`, `timeout_seconds` |
| `task.retry_requested` | `task_id`, `project_id`, `retry_count` |

`EventName` gains constants for `execution.started`, `execution.completed`, `execution.failed`, `execution.timeout`, and `task.retry_requested`; the strings are defined once there and consumed by services/orchestrator.

Routes:

| Method/path | Result |
|---|---|
| `POST /api/projects/<id>/execute` | synchronous summary: dispatched/succeeded/failed/execution IDs |
| `GET /api/projects/<id>/executions` | project executions, newest first, sanitized parsed output |
| `GET /api/projects/<id>/tasks/<id>/executions` | task executions after ownership check |
| `GET /api/executions/<id>` | one sanitized execution |
| `GET /api/projects/<id>/tasks/<id>/artifacts` | artifact metadata, newest first |
| `PATCH /api/projects/<id>/tasks/<id>/retry` | updated ready task after eligibility validation |

Malformed UUID is 400; missing project, execution, or task ownership mismatch is 404; conflict/retry-ineligible/active execution is 409; a safely cancelled request exceeding total orchestration time is 504. Unexpected errors expose neither exception traces nor credentials.

Phase 1 currently has a project-detail UI route but no task-detail UI route. Phase 2 adds `/projects/<project_id>/tasks/<task_id>` in the UI blueprint and its template; project detail renders the newest ten executions and Run Tasks control, while that task-detail page renders execution history, safe errors, Running indicator, eligible retry control, and artifact metadata with a missing-file indicator. It never offers downloads, displays source content, chain-of-thought, or fabricated test results.

## 12. Verification matrix and limits

Tests cover: all Phase 1 transition regressions; workspace creation/collision/compensation; canonical/symlink/TOCTOU boundary checks; LLM and persisted schema separation; output/error limits; Stage A dependency revalidation and index conflict; success/failure/timeout/retry events; collision-before-promotion; partial compensation with hashes; manifest crash recovery; startup ownership; APIs/UI serialization; and unsupported-role skipping.

Unit tests may use in-memory SQLite. Independent-session contention and partial-index tests use a temporary file-backed SQLite database. Tests use temporary workspaces and never execute generated tests or shell commands.

Remaining intentional limitations: one serving process, synchronous HTTP, cooperative—not forcible—LLM cancellation, SQLite lock/contention behavior, no command sandbox, and no cross-resource atomic commit. Durable manifests and recovery make the latter observable and repairable; they do not make it atomic.
