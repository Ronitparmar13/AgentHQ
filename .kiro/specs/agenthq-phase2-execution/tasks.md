# AgentHQ Phase 2 — Implementation Task Breakdown

This document derives implementation tasks directly from `.kiro/specs/agenthq-phase2-execution/requirements.md` and `design.md`. It is the implementation plan only (no code changes). The specification precedence holds: if anything conflicts, `requirements.md` takes precedence.

## Milestone dependencies (high level)

1. **M0 — Foundations & Configuration** (Req 1,3,17,18): Config + exceptions, models (Execution/Artifact), DB schema/indexes, app init prep.
2. **M1 — Workspace & Filesystem Security** (Req 1,2,11,12): WorkspaceService, FilesystemTool with boundary/symlink/TOCTOU, **WorkspaceOperations API + promotion/compensation + durable manifest primitives** (owned here).
3. **M2 — Execution Services & Registry** (Req 3,7,12,13): ExecutionService (no-commit), registry/factory interface and execution-capability configuration (no import of unfinished BackendAgent), events constants.
4. **M3 — Orchestrator & Three-Stage Execution** (Req 4,8,9,10,12,14): Orchestrator consuming WorkspaceOperations (no reimplementation), claim/execute/finalize, cancellation/timeouts, retry flow (blocked→ready), **execute and retry endpoint implementation** (owned here), **orchestration integration test with mock registered BackendAgent**.
5. **M4 — BackendAgent & Promotion/Recovery Integration** (Req 5,21): Schemas first, BackendAgent implementation second, wire into registry/completed path, integrate promotion/recovery using existing WorkspaceOperations (M1) and orchestrator hooks, **own `tests/test_execution_integration.py` (R16.6/R16.7) with real BackendAgent/orchestrator**.
6. **M5 — Remaining APIs, UI, Final Verification** (Req 6,14,15,16,19,20): Remaining list/detail/artifact APIs, response serialization/validation, UI integration, **final full-suite and Phase 1 regression verification** (earlier tests already owned by M0–M4).

**Critical path:** M0 → M1 → M2 → M3 → M4 → M5. Recovery (M4) uses WorkspaceOperations from M1. Promotion is implemented/owned by M1 (primitives), consumed by M3/M4. Retry/execute endpoints owned by M3; other endpoints owned by M5.

## Requirement coverage mapping (by requirement)
- R1 Workspace init/deletion: M0/M1
- R2 FilesystemTool + boundary + WorkspaceOperations: M1
- R3 Execution/Artifact schema + partial index: M0
- R4 Eligibility + three-stage dispatch: M3 (consumes WorkspaceOperations from M1)
- R5 BackendAgent: M4
- R6 Artifact tracking/API/UI metadata: M5
- R7 ExecutionService: M2
- R8 Orchestrator entry + endpoint: M3
- R9 Synchronous execution/timeouts: M3
- R10 Failure/retry: M3
- R11 Security constraints: M1/M4
- R12 Events: M2/M3
- R13 Agent registry: M2 (interface/factory), M4 (wire completed BackendAgent)
- R14 API endpoints: M3 (execute/retry), M5 (remaining)
- R15 UI updates: M5
- R16 Tests: owned by respective milestones (M0–M4), final verification in M5
- R17 Migrations/create_all: M0
- R18 Config/env: M0
- R19 Logging/observability: throughout
- R20 Completion criteria: M5
- R21 Startup recovery: M4 (using WorkspaceOperations from M1)


---

## M0 — Foundations & Configuration
**Goal:** Add Phase 2 config, exceptions, models (Execution/Artifact), enums/events, and DB setup prep. Preserve Phase 1 behavior.

### Dependencies
- None (build on existing).

### Tasks
- [ ] **T0.1** Add Phase 2 exceptions if missing (Req 1.3/1.4/1.6, 2.3/2.4/2.5/2.11, 5.19). Verify `WorkspaceBoundaryError`, `NotFoundError`, `ConflictError`, `ConfigurationError` exist; add `FileSizeLimitError` if needed.
  - **Maps to:** R1, R2, R5, R11
  - **Files:** `app/exceptions.py` (modify if adding)
- [ ] **T0.2** Extend configuration (Req 18). Add to `AppConfig`: `workspace_root`, `execution_timeout_seconds`, `orchestrator_timeout_seconds`, `max_retry_count`, `llm_request_timeout_seconds`, `cancellation_grace_seconds`, `agent_backend_provider`, `agent_backend_model`, **`PHASE2_STARTUP_RECOVERY_ENABLED`**. Validate types/paths; resolve relative `WORKSPACE_ROOT` to absolute; only validate backend provider/model at execution-capability boundary (Req 13.3). Update **`.env.example`** with all Phase 2 variables including `PHASE2_STARTUP_RECOVERY_ENABLED` (Req 18.5, 21.2).
  - **Maps to:** R18, R13, R21
  - **Files:** `app/config.py` (modify), `.env.example` (modify)
- [ ] **T0.3** Extend enums/events (Req 12.1, 12.6). Add to `EventName`: `EXECUTION_STARTED`, `EXECUTION_COMPLETED`, `EXECUTION_FAILED`, `EXECUTION_TIMEOUT`, `TASK_RETRY_REQUESTED`. Ensure strings defined once (no invalid Req 4 references).
  - **Maps to:** R12
  - **Files:** `app/constants.py` (modify)
- [ ] **T0.4** Add `Execution` model (Req 3.1,3.2,3.7,3.8). Fields per spec, relationship to Task with cascade delete on task. Store `output` as JSON text (primitives/<=3 levels). `retry_count` non-null default 0. Partial unique index `idx_execution_active` on `task_id` WHERE `status='in_progress'` (model-declared). Import before create_all.
  - **Maps to:** R3
  - **Files:** `app/models/execution.py` (create)
- [ ] **T0.5** Add `Artifact` model (Req 3.4,3.5,3.6). Fields per spec, FKs to execution/task/project, cascade on execution delete. No file content.
  - **Maps to:** R3, R6
  - **Files:** `app/models/artifact.py` (create)
- [ ] **T0.6** Update models package (Req 3.7, 17.2). Export `Execution`, `Artifact` in `app/models/__init__.py`; ensure imports happen before `Base.metadata.create_all(engine)`.
  - **Maps to:** R3, R17
  - **Files:** `app/models/__init__.py` (modify)
- [ ] **T0.7** Ensure schema creation (Req 17.1-17.6). Verify `Base.metadata.create_all(engine)` in `create_app()` includes new tables/indexes; idempotent; additive only for existing DBs; no Alembic in Phase 2.
  - **Maps to:** R17
  - **Files:** `app/__init__.py` (verify/modify if needed)

### Unit/verification tests (M0)
- [ ] **T0.T1** Test config parsing/defaults/validation (Req 18).
  - **Files:** `tests/test_config.py` (create/modify)
- [ ] **T0.T2** Test model schema/index declaration (Req 3.7, 17.2).
  - **Files:** `tests/test_models.py` (extend)

### Acceptance criteria (M0)
- [ ] Config loads all Phase 2 vars with defaults/validation (including `PHASE2_STARTUP_RECOVERY_ENABLED`).
- [ ] `.env.example` updated with all Phase 2 variables.
- [ ] Execution/Artifact models created with correct constraints/cascades.
- [ ] Partial unique index `idx_execution_active` declared on model and present after create_all.
- [ ] **Run the existing Phase 1 test suite before closing this milestone. All existing Phase 1 tests must remain passing without modification.**
- [ ] All existing Phase 1 models/tests unaffected.


## M1 — Workspace & Filesystem Security
**Goal:** Isolated workspaces, hardened filesystem tool, **secure WorkspaceOperations API + promotion, compensation, durable manifest primitives** (owned here).

### Dependencies
- M0 (config/exceptions/models)

### Tasks
- [ ] **T1.1** Implement `WorkspaceService` (Req 1.1-1.7). Methods: `get_workspace_path(session, project_id)` (validate UUID4, project exists, return canonical absolute without child ops), `create_for_project(...)`, `delete_for_project(...)` with safe delete before commit and failure handling. **Create `.staging/` and the private `.recovery/` directory with the workspace** (Design §6).
  - **Maps to:** R1
  - **Files:** `app/services/workspace_service.py` (create)
- [ ] **T1.2** Refactor project creation coordination if needed (Req 1.1). Support noncommitting transaction flow consistent with design.
  - **Maps to:** R1
  - **Files:** `app/services/project_service.py` (modify as needed)
- [ ] **T1.3** Implement `FilesystemTool` (Req 2.1-2.11). Class in `app/tools/filesystem.py`. Constructor takes `workspace_root: Path`. Enforce no absolute/`~`/`..`, canonicalize root, reject symlinks in any component, containment via `is_relative_to` (not string prefix), TOCTOU defense (re-verify after descriptor open where possible), create parents on write, 10MB limit enforcement, never log content. Methods: `read_file`, `write_file`, `list_directory`, `file_exists`, `file_exists_at_destination`.
  - **Maps to:** R2, R11
  - **Files:** `app/tools/filesystem.py` (create), `app/tools/__init__.py` (create if needed)
- [ ] **T1.4** Implement `WorkspaceOperations` (Req 2.12, 4.15-4.28). **Sole privileged abstraction** for: secure filesystem promotion, hash-verified compensation, durable manifest creation and updates, and recovery filesystem cleanup. Apply same canonical containment, symlink rejection, descriptor revalidation to sources/dests, no-replace semantics, hash verification, batch collision detection before promotion. **Manifest lifecycle statuses (exact):** `prepared`, `promoting`, `completed`, `compensation_failed`, `database_pending`. **Per-file promotion statuses:** `prepared`, `promoting`, `promoted`, `compensated` (not manifest lifecycle statuses). **Must NOT** own database transactions, Execution or Task state updates, or EventService recording — those belong to `ExecutionOrchestrator` and appropriate services. No raw Path/shutil bypass.
  - **Maps to:** R2, R4
  - **Files:** `app/services/workspace_operations.py` (create)
- [ ] **T1.5** Define promotion manifest format and helpers (Req 4.23-4.28, design §6). Create/read/update durable manifest JSON with required fields; support relocation to `workspace/<project-id>/.recovery/` if needed; fsync discipline; validate paths independently.
  - **Maps to:** R4, R21
  - **Files:** `app/services/promotion_manifest.py` (create) or integrated into WorkspaceOperations

### Unit tests (M1)
- [ ] **T1.T1** Filesystem tool tests (Req 16.3). Read/write, `..`/absolute rejection, symlink escape, parent dir creation, TOCTOU.
  - **Files:** `tests/test_filesystem_tool.py` (create)
- [ ] **T1.T2** Workspace service tests (Req 1).
  - **Files:** `tests/test_workspace_service.py` (create)
- [ ] **T1.T3** **WorkspaceOperations tests (Req 2.12, 4.22-4.28, 16.14-16.19)**. Coverage: collision rejection before promotion, no-overwrite of pre-existing files, path/symlink security, manifest persistence/lifecycle, partial promotion failure, hash-verified compensation, compensation failure handling.
  - **Files:** `tests/test_workspace_operations.py` (create)

### Acceptance criteria (M1)
- [ ] Workspaces created with `.staging/` and private `.recovery/`; UUID4 validation enforced.
- [ ] FilesystemTool blocks traversal/symlinks/absolute paths; TOCTOU considerations implemented.
- [ ] WorkspaceOperations is the sole privileged API with manifest-driven promotion/compensation and hash verification.
- [ ] All WorkspaceOperations security/collision/compensation cases tested in `tests/test_workspace_operations.py`.
- [ ] **Run the existing Phase 1 test suite before closing this milestone. All existing Phase 1 tests must remain passing without modification.**


## M2 — Execution Services & Registry
**Goal:** Execution/Artifact persistence (no-commit), events, registry/factory interface and execution-capability configuration. **Do not import unfinished BackendAgent.**

### Dependencies
- M0, M1

### Tasks
- [ ] **T2.1** Implement `ExecutionService` (Req 7.1-7.7). Methods: `create_execution`, `update_execution_status` (sets completed_at on terminal), `get_execution`, `list_executions(session, *, task_id=None, project_id=None)` (exactly one scope), `create_artifact`. No commits/rollbacks; truncate errors to 500 chars with `[truncated]` if needed.
  - **Maps to:** R7, R11
  - **Files:** `app/services/execution_service.py` (create)
- [ ] **T2.2** Execution/artifact tests (Req 3, 7, 16.8-16.9).
  - **Files:** `tests/test_execution_service.py` (create)
- [ ] **T2.3** Update agent registry/factory for execution capability (Req 13.1-13.5). `build_registry(llm_router, app_config)` accepts params; execution-capability factory interface established to instantiate BackendAgent when enabled. **No module-level import of `app.agents.backend` in M2.** Use a **lazy import** inside the Backend execution-capability factory, only when execution capability is enabled. M4 supplies and registers the completed BackendAgent. Validate `AGENT_BACKEND_PROVIDER`/`AGENT_BACKEND_MODEL` only at this capability boundary when enabling execution (raise ConfigurationError if missing at that boundary). Preserve Phase 1 startup without BackendAgent imports or Backend-specific configuration. Keep stubs for designer/frontend/qa/utility.
  - **Maps to:** R13
  - **Files:** `app/agents/__init__.py` (modify)
- [ ] **T2.4** Ensure event constants used (Req 12).
  - **Maps to:** R12
  - **Files:** `app/constants.py` (M0), consumed by services/orchestrator

### Acceptance criteria (M2)
- [ ] ExecutionService enforces API contract, no commits.
- [ ] Registry/factory interface supports enabling BackendAgent execution with **no module-level import of `app.agents.backend`**; lazy import only when enabled. Config validation only at capability boundary. Phase 1 startup unaffected.
- [ ] Models/cascades and partial index verified.
- [ ] **Run the existing Phase 1 test suite before closing this milestone. All existing Phase 1 tests must remain passing without modification.**


## M3 — Orchestrator & Three-Stage Execution
**Goal:** Core orchestration consuming WorkspaceOperations (no reimplementation), claim/execute/finalize, cancellation/timeouts, retry, events. **Own execute and retry endpoints.** **Add orchestration integration test with mock registered BackendAgent.**

### Dependencies
- M0-M2 (and M1 WorkspaceOperations must be available)

### Tasks
- [ ] **T3.1** Extend TaskService for Phase 2 transitions (Req 4, 10.3). Add noncommitting transition support so orchestrator/routes can use caller-owned transactions. Validate against `TASK_TRANSITIONS`; **add `blocked → ready`** (Req 4/10). Keep existing `update_task_status` as committing wrapper for compatibility. Record `task.status_changed` via EventService in caller-owned transaction (flush only). Ensure `blocked → in_progress` remains supported.
  - **Maps to:** R4, R10, Phase 1 compatibility
  - **Files:** `app/services/task_service.py` (modify), `app/constants.py` (ensure transitions)
- [ ] **T3.2** Implement `ExecutionOrchestrator` (Req 4.1-4.28, 8.1-8.9, 9.1-9.7). Class in `app/orchestration/orchestrator.py`. Constructor takes session_factory, agent_registry, WorkspaceService, WorkspaceOperations, ExecutionService, AppConfig. Methods: `identify_eligible_tasks(session, project_id)` (ready, no in-progress exec, role in SUPPORTED_ROLES={backend}, order by priority rank high=3/med=2/low=1 desc then created_at asc), `dispatch_task(project_id, task_id)` (owns fresh sessions per stage), `execute_ready_tasks(project_id)`. **Orchestrator must consume WorkspaceOperations for promotion/compensation (no reimplementation of filesystem promotion logic).**
  - **Maps to:** R4, R8, R9
  - **Files:** `app/orchestration/__init__.py` (create), `app/orchestration/orchestrator.py` (create)
- [ ] **T3.3** Stage A implementation (Req 4.6-4.8). Fresh transaction: re-fetch task/project, verify ready/supported role/all prerequisites done/no in-progress, calculate retry_count from completed terminal executions, transition task to in_progress via noncommitting service, create execution via ExecutionService, record `execution.started` (retry_count, attempt_number = retry_count+1), commit. On partial unique index conflict -> `ConflictError`.
  - **Maps to:** R4, R12
- [ ] **T3.4** Stage B implementation (Req 4.9-4.14, 9.2). After commit create staging dir. Build Agent_Context with canonical paths, staging-bound FilesystemTool, llm_router, execution deadline (EXECUTION_TIMEOUT_SECONDS), execution-scoped cancellation token (never ambient env vars; only allowlisted). Retrieve agent from registry and call `agent.run(task, context)`. No DB transaction. Validate AgentResult.output size if success (<=100000 chars serialized) else treat as failure. Cooperative cancellation; timeout signals cancellation, wait up to CANCELLATION_GRACE_SECONDS for acknowledgement - if missing, leave execution in_progress with staging/manifest for recovery (no finalize/cleanup/retry). Pass deadline/token through LLM path per design (effective timeout = min(LLM_REQUEST_TIMEOUT_SECONDS, remaining execution deadline) when deadline exists).
  - **Maps to:** R4, R9, R11
- [ ] **T3.5** Stage C implementation (Req 4.15-4.28). No DB transaction during promotion. **Success path:** batch collision check before any promotion (entire batch rejected if any destination exists). If ok, use **WorkspaceOperations** to promote with manifest tracking (`promoting`/`promoted` per file), create artifacts, update execution to success with output JSON, transition task to `review`, record events (`task.status_changed`, `execution.completed` with duration_ms/artifact_count), commit tx. Only after commit mark manifest `completed` and delete staging+manifest.

  **Three explicit and independent failure paths:**

  **A. Agent failure before promotion**
  1. Open a fresh database transaction.
  2. Persist execution failure, task blocked status and failure events.
  3. Commit successfully.
  4. Clean staging.

  **B. Promotion failure**
  1. Stop all further promotion.
  2. Compensate only manifest-owned promoted regular files with matching SHA-256 (via WorkspaceOperations).
  3. Update the manifest with compensation results.
  4. Open a fresh database transaction.
  5. Persist execution failure, task blocked status and failure event.
  6. Commit.
  7. Delete staging/manifest only when compensation and failure persistence have succeeded; otherwise retain or relocate the manifest.

  **C. Database finalization failure after promotion**
  1. Retain the durable manifest with `database_pending`.
  2. Preserve promoted files and recovery information.
  3. Do not mark the manifest `completed`.
  4. Do not automatically retry finalization.
  5. Let startup recovery reconcile authoritative persisted database state.

  **Timeouts:** must still obey the cancellation acknowledgement contract. Missing acknowledgement means no finalization, cleanup or retry.
  - **Maps to:** R4, R6, R9, R12
  - **Files:** `app/orchestration/orchestrator.py` (modify)
- [ ] **T3.6** **Execute endpoint (owned by M3)** (Req 8.8-8.9, 9.1, 14.1). POST `/api/projects/<project_id>/execute` validates project exists, calls orchestrator.execute_ready_tasks, returns summary. Return 200 with zeros if none eligible. Handle per design.
  - **Maps to:** R8, R9, R14
- [ ] **T3.7** **Retry endpoint (owned by M3)** (Req 10.1-10.7, 14.5). PATCH `/api/projects/<project_id>/tasks/<task_id>/retry` validates ownership, status==blocked, latest terminal execution retry_count < max_retry_count (default 2). Use noncommitting TaskService transition in route-owned transaction to move blocked→ready, record `task.retry_requested` via EventService in same transaction, commit. Route must not call EventService directly or use committing TaskService inside larger tx. Return 409 if ineligible.
  - **Maps to:** R10, R12, R14

### Unit/integration tests (M3)
- [ ] **T3.T1** Orchestrator unit tests (Req 16.5). Eligible filtering/ordering, three-stage dispatch, failure path, partial unique index conflict, retry count increment, timeout handling, staging cleanup, blocked→ready→in_progress chain.
  - **Files:** `tests/test_execution_orchestrator.py` (create)
- [ ] **T3.T2** Retry/transition tests (Req 16.10). **Explicitly test `blocked → in_progress` remains valid for Phase 1 compatibility. Explicitly test `blocked → ready → in_progress` works for the new Phase 2 retry flow.**
  - **Files:** extend tests
- [ ] **T3.T3** Event payload tests (Req 16.11). Include **`execution.timeout` event payload with `timeout_seconds`** (Req 12.5).
  - **Files:** extend tests
- [ ] **T3.T4** **Orchestration integration test with mock registered BackendAgent (Req 4, 8, 16)**. Using a mock registered BackendAgent: verify a zero-prerequisite backend task becomes ready through normal task-service dependency evaluation; `execute_ready_tasks()` dispatches the eligible backend task; unsupported roles remain ready; no manual task-status manipulation required.
  - **Files:** `tests/test_execution_orchestrator_integration.py` (create) or extend `tests/test_execution_orchestrator.py`

### Acceptance criteria (M3)
- [ ] Three-stage execution uses fresh sessions per stage; no DB tx during Stage B.
- [ ] Orchestrator consumes WorkspaceOperations for promotion/compensation (no duplication).
- [ ] Partial unique index enforced (conflict -> ConflictError).
- [ ] Execute and retry endpoints implemented here with correct transaction boundaries.
- [ ] Unsupported roles skipped.
- [ ] Orchestration integration test with mock registered BackendAgent passes.
- [ ] **Run the existing Phase 1 test suite before closing this milestone. All existing Phase 1 tests must remain passing without modification.**


## M4 — BackendAgent & Promotion/Recovery Integration
**Goal:** Schemas first, BackendAgent second, wire into registry/completed path, integrate promotion/recovery using existing WorkspaceOperations (M1) and orchestrator hooks. **Own `tests/test_execution_integration.py` (R16.6/R16.7).**

### Dependencies
- M0-M3 (M1 WorkspaceOperations required; M2 registry interface required; M3 orchestrator hooks available)

### Tasks
- [ ] **T4.1** **Define Pydantic schemas first** (Req 5.5-5.6). Create LLM response schema (summary, files with relative_path/content/purpose/file_type, next_steps) and persisted output schema (summary, files metadata with relative_path/size_bytes/file_type/purpose, next_steps). Enforce constraints (primitives/<=3 levels) and size limits.
  - **Maps to:** R5
  - **Files:** `app/agents/backend.py` or `app/agents/schemas.py` (create)
- [ ] **T4.2** **Implement BackendAgent second** (Req 5.1-5.24). `app/agents/backend.py`: subclass BaseAgent, name="Backend", role=backend. Accept llm_router, model_config. `run(task, context)` builds prompt with title/description/staging path, calls `llm_router.complete(role="BACKEND", prompt=...)`, validates response size (<=100000), parses JSON, validates against LLM schema. If invalid -> failure "Invalid LLM response format". Write each content to staging via `context["filesystem_tool"].write_file()` (staging path only). Enforce 10MB file size via tool. Return AgentResult with persisted-output schema only (no content/raw response/CoT). No DB/events/status changes. Handle WorkspaceBoundaryError -> failure. May generate test files but not executed.
  - **Maps to:** R5, R11
- [ ] **T4.3** **Wire BackendAgent into registry** (Req 13.2, 13.5). Using M2 factory interface with lazy import, register `BackendAgent(llm_router, app_config.backend_model_config)` when execution capability enabled and config valid; ensure wiring does not break Phase 1. Validate backend config only at capability boundary (Req 13.3).
  - **Maps to:** R13
  - **Files:** `app/agents/__init__.py` (modify)
- [ ] **T4.4** **Promotion/recovery integration** (Req 4.15-4.28, 21.1-21.12). Ensure orchestrator uses WorkspaceOperations from M1 as implemented. Implement `startup_recovery()` / recovery service using WorkspaceOperations APIs (no reimplementation of promotion logic). Follow exact recovery order: identify in_progress executions (don't change for manifest alone), discover all manifests in `.staging/` and `.recovery/` across projects, validate against Execution/Task/Artifact with canonical/symlink/hash/ownership checks. Handle success+review+artifacts (complete manifest, clean temp), in_progress with interrupted promotion (hash-verified compensation of promoted entries only), database_pending (use persisted state as authoritative), then persist terminal state for remaining in_progress in fresh tx, then delete validated abandoned staging dirs. No arbitrary deletion. Lock/once guard.
  - **Maps to:** R21, R4
  - **Files:** `app/services/recovery_service.py` (create), integrate into `app/__init__.py` create_app()
- [ ] **T4.5** Integrate recovery into app startup (Req 21.2, 17). Call recovery after create_all/registry setup, before serving routes. Respect flags/env (`PHASE2_STARTUP_RECOVERY_ENABLED`, Werkzeug reload behavior).
  - **Maps to:** R21, R17
  - **Files:** `app/__init__.py` (modify)

### Tests (M4)
- [ ] **T4.T1** BackendAgent unit tests (Req 16.4). Success parsing, file creation to staging, invalid JSON/schema -> failure, boundary violation -> failure, proper AgentResult structure.
  - **Files:** `tests/test_backend_agent.py` (create)
- [ ] **T4.T2** Promotion/recovery integration tests (Req 16.14-16.19, 21). Collision batch rejection, partial promotion failure + compensation, crash during promotion + recovery, compensation failure handling, manifest lifecycle. Use WorkspaceOperations APIs.
  - **Files:** `tests/test_promotion_recovery.py` (create)
- [ ] **T4.T3** Startup recovery tests (Req 21, 16.17).
  - **Files:** `tests/test_startup_recovery.py` (create)
- [ ] **T4.T4** Cancellation tests (Req 16.20, 9.2). Token checks before/after provider calls and before writes, acknowledged cancellation prevents post-cancellation writes/finalization/cleanup/retry, missing acknowledgement retains in_progress execution and staging directory for startup recovery.
  - **Files:** extend `tests/test_execution_orchestrator.py`
- [ ] **T4.T5** **End-to-end integration test ownership (Req 16.6, 16.7)**. Create and own `tests/test_execution_integration.py` covering: project creation through Manager planning with mock LLM responses; backend task identified through normal project/task service calls; real BackendAgent and orchestrator execution; temporary file-backed SQLite database; staging-to-workspace promotion; artifact metadata persistence; execution success and task review state; unsupported-role tasks remain ready. No generated tests or shell commands executed.
  - **Files:** `tests/test_execution_integration.py` (create)

### Acceptance criteria (M4)
- [ ] Schemas defined first, BackendAgent implemented second, wired via M2 factory interface with lazy import.
- [ ] Promotion/recovery use WorkspaceOperations from M1 (no duplication).
- [ ] Recovery follows exact order, no arbitrary deletion, hash-verified compensation.
- [ ] `tests/test_execution_integration.py` exists and covers R16.6/R16.7.
- [ ] All M4 tests implemented in owning milestone.
- [ ] **Run the existing Phase 1 test suite before closing this milestone. All existing Phase 1 tests must remain passing without modification.**


## M5 — Remaining APIs, UI, Final Verification
**Goal:** Remaining endpoints (not execute/retry), serialization/validation, UI integration, **final full-suite and Phase 1 regression verification**.

### Dependencies
- M0-M4

### Tasks
- [ ] **T5.1** **Remaining API endpoints (Req 14.2-14.4, 14.6-14.7, 6.3)**. Implement only endpoints not owned by M3:
  - GET `/api/projects/<project_id>/executions` (newest first, sanitized parsed output)
  - GET `/api/projects/<project_id>/tasks/<task_id>/executions`
  - GET `/api/executions/<execution_id>` (detail) — **How it obtains/validates associated project/task**: use existing `Execution` record to get `project_id` and `task_id`; validate existence/ownership via existing lookups in the current application data model/request context (no new authz architecture). If the model/lookup path cannot guarantee cross-validation without adding authz, explicitly record that limitation here and enforce what is possible with existing patterns (404 on missing/invalid references).
  - GET `/api/projects/<project_id>/tasks/<task_id>/artifacts` (newest first, metadata-only)
  Validate ownership/project/task existence; correct status codes (400 malformed UUID, 404 not found/ownership mismatch). Ensure serialization matches requirements.
  - **Maps to:** R6, R14
  - **Files:** `app/routes/api.py` (modify), `app/routes/helpers.py` (modify if needed)
- [ ] **T5.2** Artifact/UI metadata integration (Req 6.1-6.6). Ensure artifact records exposed correctly; no download endpoint.
  - **Maps to:** R6
- [ ] **T5.3** UI updates (Req 15.1-15.6). Add task detail route/template at `/projects/<project_id>/tasks/<task_id>` if missing. Project detail: "Executions" section (newest 10), "Run Tasks" button calling execute endpoint with status message. Task detail: "Execution History", safe errors, Running indicator for in_progress, Retry button if blocked and retry_count < max_retry_count, artifacts with missing-file indicator. No downloads/source/CoT/test results.
  - **Maps to:** R15
  - **Files:** `app/routes/ui.py` (modify), `templates/project_detail.html` (modify), `templates/task_detail.html` (create), `static/` (style if needed)
- [ ] **T5.4** Logging/observability pass (Req 19). Ensure appropriate logs, no sensitive data.
  - **Maps to:** R19
- [ ] **T5.5** **Final verification & regression (Req 16, 20)**. Verify all tests from M0-M4 exist and are correctly placed. Run/verify **full test suite** and **all Phase 1 tests continue to pass without modification** (final complete regression verification). Ensure fixtures in `tests/conftest.py`: `mock_llm_router` returning configurable stub, `test_workspace` creating temp workspace and cleaning up. Confirm coverage of all Req 16 items. Phase 2 must not execute shell commands or generated tests.
  - **Maps to:** R16, R20
  - **Files:** `tests/conftest.py` (ensure fixtures)
- [ ] **T5.6** Manual verification script (Req 20.2). Create `tests/manual_phase2_verification.py` exercising full flow with real DB, **mock LLM responses**, and verify staging create/cleanup and all transitions. **Must use mock LLM responses and require no live provider credentials.**
  - **Maps to:** R20
  - **Files:** `tests/manual_phase2_verification.py` (create)
- [ ] **T5.7** Completion checklist (Req 20.1). Verify all 21 requirements have tests, manual verification succeeds (mock LLM, no live credentials), Phase 1 tests pass, BackendAgent produces files, coverage targets noted, no scope expansion. **Explicitly confirm the manual verification script uses mock LLM responses and requires no live provider credentials.**
  - **Maps to:** R20

### Acceptance criteria (M5)
- [ ] Only remaining APIs implemented here (execute/retry owned by M3).
- [ ] UI complete with correct states and no disallowed content.
- [ ] Final full-suite and Phase 1 regression verification completed (all Phase 1 tests pass without modification).
- [ ] Manual verification script exists and uses mock LLM responses with no live provider credentials.
- [ ] Completion checklist satisfied.


---

## Files expected to be created/modified (summary)

**Created:**
- `app/models/execution.py`
- `app/models/artifact.py`
- `app/tools/__init__.py`, `app/tools/filesystem.py`
- `app/services/workspace_service.py`, `app/services/execution_service.py`, `app/services/workspace_operations.py`, `app/services/promotion_manifest.py` (or integrated), `app/services/recovery_service.py`
- `app/orchestration/__init__.py`, `app/orchestration/orchestrator.py`
- `tests/test_filesystem_tool.py`, `tests/test_workspace_service.py`, `tests/test_workspace_operations.py` (M1), `tests/test_execution_service.py`, `tests/test_execution_orchestrator.py`, `tests/test_execution_orchestrator_integration.py` (M3), `tests/test_backend_agent.py`, `tests/test_execution_integration.py` (M4), `tests/test_promotion_recovery.py`, `tests/test_startup_recovery.py`, `tests/manual_phase2_verification.py`

**Modified:**
- `app/exceptions.py` (add `FileSizeLimitError` if missing)
- `app/config.py` (Phase 2 config including `PHASE2_STARTUP_RECOVERY_ENABLED`)
- `.env.example` (add all Phase 2 variables including `PHASE2_STARTUP_RECOVERY_ENABLED`)
- `app/constants.py` (EventName + ensure `blocked → ready`)
- `app/models/__init__.py`
- `app/__init__.py` (create_app wiring: recovery, registry)
- `app/services/task_service.py` (noncommitting transitions)
- `app/services/project_service.py` (coordination if needed)
- `app/agents/__init__.py` (registry/factory interface M2 with lazy import; wire BackendAgent M4)
- `app/agents/backend.py` (schemas M4.1, implementation M4.2)
- `app/routes/api.py`, `app/routes/ui.py`, `app/routes/helpers.py`
- `templates/project_detail.html`, `templates/task_detail.html` (create)
- `tests/conftest.py` (fixtures)

## Ambiguities / unresolved implementation questions
- **Transaction boundaries in routes:** Retry must use route-owned transaction with noncommitting TaskService + EventService in same transaction; need exact service method signatures to avoid mixing committing/noncommitting paths.
- **Manifest relocation timing:** When to copy manifest from staging to `.recovery/` vs keeping in staging - must follow design without deleting before reconciliation.
- **Cancellation propagation:** Thread token/deadline through existing LLM code paths without breaking Phase 1 Manager calls (deadline/token absent).
- **Partial index on SQLite:** Model-declared partial unique index must be imported before create_all; ensure compatibility and test with file-backed DB.
- **WorkspaceOperations API surface:** Exact method signatures for promotion/compensation/recovery need to align with orchestrator without bypassing boundaries.
- **Recovery lock details:** Implement per-process once guard + exclusive startup lock as specified (cross-process lock mechanism details to follow design).
- **Task priority ordering:** SQL ordering by priority rank (high=3, medium=2, low=1) - ensure correct mapping.
- **Staging cleanup timing:** Only after DB commit success for success path; only after failure persistence/compensation per rules.
- **Backend model config validation:** Only at execution-capability boundary (Req 13.3).
- **Execution detail endpoint ownership/validation:** `GET /api/executions/<execution_id>` will use the `Execution` record's `project_id`/`task_id` for validation against existing lookups in the current data model/request context with no new authz architecture. If full cross-validation isn't possible with existing patterns without introducing authz, this is a known limitation to enforce as much as possible and return 404 appropriately.

## Corrections applied (summary)
1. **Req references:** Removed invalid references to Req 4.30 and 4.34; used only valid Req IDs.
2. **WorkspaceOperations ownership:** M1 implements secure WorkspaceOperations API + promotion/compensation + durable manifest primitives with `tests/test_workspace_operations.py`. M3 consumes it (no reimplementation). M4 uses it for recovery. T1.1 adds `.recovery/` directory creation.
3. **BackendAgent registry:** M2 establishes registry/factory interface with **no module-level import of `app.agents.backend`**, lazy import only when enabled, config validation only at capability boundary; M4 implements BackendAgent and wires it in.
4. **API endpoints:** Execute and retry owned by M3; remaining list/detail/artifact APIs + serialization/UI in M5 (single owner). T5.1 clarifies execution-detail validation approach.
5. **M4 reorder:** Schemas first (T4.1), BackendAgent second (T4.2), wiring third (T4.3), promotion/recovery integration fourth (T4.4). T4.T5 owns `tests/test_execution_integration.py` (R16.6/R16.7).
6. **Tests ownership:** All tests placed in owning milestones; M3 gets orchestration integration test with mock registered BackendAgent (T3.T4); M5 does final full-suite and Phase 1 regression verification.
7. **Phase 1 regression gates:** Explicit acceptance criterion added to M0–M4 requiring Phase 1 test suite to pass unchanged before closing each milestone; M5 does final complete verification.
8. **Transitions:** T3.T2 explicitly tests both `blocked → in_progress` (Phase 1 compat) and `blocked → ready → in_progress` (Phase 2 retry).
9. **Config:** Added `PHASE2_STARTUP_RECOVERY_ENABLED` to config and `.env.example`.
10. **Events:** T3.T3 explicitly tests `execution.timeout` payload with `timeout_seconds`.
11. **Manual verification:** T5.6/T5.7 explicitly require mock LLM responses and no live provider credentials.
12. **Security/retry/cancellation/manifest/recovery/compatibility:** Preserved throughout.

## Milestone dependencies summary
M0→M1→M2→M3→M4→M5. M1 provides WorkspaceOperations (.staging + .recovery); M2 provides registry interface with lazy Backend import; M3 provides orchestrator/endpoints (execute/retry) + orchestration integration test; M4 uses all above for agent+recovery + owns full integration test; M5 completes remaining APIs/UI and final verification with Phase 1 regression gate.
