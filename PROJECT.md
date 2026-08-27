# AgentHQ

## 1. Product Definition

**AgentHQ** is an autonomous AI software company presented as a virtual office.

The user acts as the **CEO/client**. The user provides a software project requirement to a **Manager Agent**. The Manager analyzes the requirement, creates a plan, decomposes work into tasks, assigns work to specialist agents, tracks dependencies, reviews deliverables, and coordinates rework until the project satisfies its acceptance criteria.

The initial team:

- Manager
- UI/UX Designer
- Frontend Developer
- Backend Developer
- QA Engineer
- HR Analyst
- Utility Agent

The core product loop is:

`CEO → Manager → Specialists → QA → Rework if needed → Manager approval → Delivery`

The UI should make the underlying agent activity visible and understandable without exposing private chain-of-thought.

## 2. Product Principles

1. **Manager-led orchestration:** The user gives projects to the Manager rather than micromanaging individual agents.
2. **Real work, not fake activity:** Activity, progress, task status, and agent messages must come from actual system state whenever functionality exists.
3. **Structured communication:** Agents communicate through typed messages, task updates, and artifacts.
4. **Tool-grounded execution:** LLMs decide what to do; tools perform file, Git, Graphify, test, and other operations.
5. **Shared project state:** Tasks, decisions, artifacts, messages, and statuses persist in the database.
6. **Model independence:** Agent logic must not be tightly coupled to a single model provider.
7. **Safe execution:** Autonomous code execution must be restricted to controlled project workspaces and, later, sandboxed containers.
8. **Incremental complexity:** Start with a small working loop before adding production infrastructure.
9. **Observable system:** Every meaningful state transition should be traceable through activity/events.
10. **Human control:** The CEO can pause, inspect, approve, reject, or stop a project.

## 3. MVP Goal

The first genuine MVP must complete one small software project through a real agent loop.

Target flow:

1. CEO submits a project.
2. Manager analyzes requirements.
3. Manager creates structured tasks and dependencies.
4. Designer creates a design specification.
5. Frontend and Backend agents implement their assigned work.
6. QA inspects and tests the work.
7. QA reports failures as structured issues.
8. Relevant developer receives a repair task.
9. QA verifies the repair.
10. Manager reviews project acceptance criteria.
11. Project is marked delivered.

A small project such as an animated portfolio or simple SaaS dashboard is sufficient for the MVP.

## 4. Initial Agent Responsibilities

### Manager
Owns project planning, delegation, prioritization, dependency management, review, escalation, and final acceptance.

### UI/UX Designer
Produces user flows, design specifications, component guidance, interaction requirements, and visual/UX artifacts.

### Frontend Developer
Implements UI and client-side behavior using approved design specifications and backend contracts.

### Backend Developer
Implements APIs, persistence, business logic, validation, authentication where required, and API contracts.

### QA Engineer
Creates test plans, runs available tests/checks, records defects with evidence, and verifies fixes.

### HR Analyst
Provides workforce/workload/performance views in later MVP stages. It is not part of the critical build loop initially.

### Utility Agent
Handles small bounded tasks such as summarization, formatting, transformation, or other low-risk supporting work.

## 5. Agent Model Strategy

Models are configured by role rather than hard-coded throughout the application.

Use a configuration layer such as:

- `manager`
- `designer`
- `frontend`
- `backend`
- `qa`
- `hr`
- `utility`

Each role maps to a provider/model configured through environment/configuration.

The system must support changing the underlying model without changing the agent's business logic.

Do not store API keys in source code or commit them to Git.

## 6. Project State

A project contains:

- Requirements
- Acceptance criteria
- Tasks
- Dependencies
- Agents
- Messages
- Decisions
- Artifacts
- Files
- Test results
- Defects
- Activity/events
- Current status

Project lifecycle:

`draft → planning → in_progress → review → blocked (optional) → delivered / cancelled`

Task lifecycle:

`backlog → ready → in_progress → review → blocked / rework → done`

## 7. Communication

Agent communication is structured and persistent.

Examples:

- `task_assignment`
- `task_started`
- `artifact_created`
- `task_review_requested`
- `bug_report`
- `bug_fixed`
- `dependency_blocked`
- `approval_requested`
- `approval_granted`
- `project_completed`

Never depend on parsing free-form chat to determine system state when a structured field can represent it.

## 8. Memory Strategy

AgentHQ uses different memory layers for different purposes:

### Operational memory
SQLite initially, PostgreSQL later.

Stores tasks, statuses, messages, decisions, agent state, artifacts, and project metadata.

### Project/code intelligence
Graphify.

Used to understand repository structure, relationships, dependencies, and code concepts.

### Context summaries
Persisted summaries of important completed work can be stored in the database and injected into later agent runs.

Graphify is **not** a replacement for operational state or agent memory.

## 9. UI Vision

The UI should preserve the virtual-office concept:

- Dashboard
- Projects
- Office
- Tasks
- Team
- Activity
- Files
- Settings

Important visual states:

- Working
- Waiting
- Reviewing
- Blocked
- Idle

The UI should visualize real state from the backend.

Do not simulate completion merely to make the interface look active.

## 10. Out of Scope for Initial MVP

Do not start with:

- Kubernetes
- microservices
- Redis/Kafka
- vector databases
- complex event infrastructure
- multi-tenant billing
- dynamic hiring
- autonomous production deployment
- unrestricted shell execution
- large-scale distributed workers

Add these only when a demonstrated requirement justifies them.

## 11. Definition of Done for MVP

The MVP is complete when:

- A CEO can create a project from the UI.
- A real Manager LLM produces a structured plan.
- Tasks are persisted.
- Specialist agents can receive and complete tasks.
- Agents can exchange structured messages.
- QA can produce a real defect.
- A developer can perform rework.
- QA can verify the fix.
- The Manager can approve completion.
- The activity feed reflects actual events.
- Secrets are not committed.
- Automated tests cover the core orchestration logic.
