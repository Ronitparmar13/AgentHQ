# AgentHQ AI Development Rules

This file is the shared operating contract for AI coding assistants working on AgentHQ.

## 1. Before Changing Code

Always read:

1. `PROJECT.md`
2. `ARCHITECTURE.md`
3. this file

Then inspect the existing implementation before proposing a replacement.

Do not redesign the architecture merely because you prefer another framework.

## 2. Project Goal

AgentHQ is an autonomous AI software company.

The core experience is:

`CEO → Manager → Specialist Agents → QA → Rework → Approval → Delivery`

The application must prioritize real orchestration and reliable state over cosmetic simulation.

## 3. Technology Constraints

Current intended stack:

- Python 3.12
- Flask
- Jinja2
- HTML/CSS/JavaScript
- SQLAlchemy
- SQLite initially
- PostgreSQL later
- Custom Python agent runtime
- Graphify for code/project intelligence

Do not add LangChain, CrewAI, LangGraph, Redis, Kafka, Kubernetes, or another major framework unless a concrete requirement is documented first and the trade-off is understood.

## 4. Coding Style

Prefer:

- small modules
- clear names
- type hints
- Pydantic for external/LLM data validation
- SQLAlchemy models for persistence
- services for business logic
- explicit error handling
- testable pure functions where possible

Avoid:

- giant files
- hidden global state
- circular imports
- duplicated provider logic
- magic strings spread across the codebase
- unnecessary abstractions

## 5. Agent Rules

An agent consists of:

- role
- instructions
- model configuration
- available tools
- task/context input
- structured output

Do not hard-code a specific provider into business logic.

Do not make one agent responsible for another agent's database internals.

Agents should communicate using structured messages/events.

## 6. LLM Output

Treat model output as untrusted input.

Validate structured output before using it.

For example:

```text
LLM
 ↓
raw output
 ↓
Pydantic validation
 ↓
application logic
 ↓
database/tool action
```

Never execute arbitrary code just because an LLM returned it.

## 7. Tool Rules

The LLM decides which tool to use.

The application controls what the tool is allowed to do.

Tools must:

- validate arguments
- enforce project boundaries
- return structured results
- capture errors
- avoid unnecessary side effects

Filesystem access must remain inside the active project workspace.

Command execution must use an allowlist until a proper sandbox exists.

## 8. Secrets

Never:

- hard-code API keys
- commit `.env`
- print secret values in logs
- expose secrets to the browser

Use environment variables and `.env.example`.

## 9. Graphify

Graphify is used for:

- repository understanding
- code relationships
- project/code recall
- dependency exploration

Graphify is not the operational database.

Do not put task status, agent state, or approvals into Graphify.

## 10. Database

SQLite is the MVP database.

Use SQLAlchemy so PostgreSQL can be introduced later.

Do not write business logic that depends on SQLite-only behavior.

## 11. UI Rules

The virtual office is the presentation layer for real system state.

Do not fabricate:

- task completion
- progress percentage
- agent activity
- QA results
- project delivery

When the backend does not have real activity yet, display an explicit empty/loading state.

Never expose private chain-of-thought. The UI may show concise, user-safe activity summaries such as:

`Analyzing requirements`

`Inspecting repository`

`Running tests`

`Reviewing deliverable`

## 12. Testing

Before declaring a feature complete:

- run the relevant unit tests
- test success and failure paths
- test malformed model output
- test tool permission boundaries
- test database state transitions

Critical orchestration code must have automated tests.

## 13. Git Rules

Use small, meaningful commits.

Preferred format:

```text
feat: add manager task planner
feat: add qa defect workflow
fix: prevent duplicate task assignment
test: cover dependency resolution
refactor: isolate llm provider router
```

Never commit:

- `.env`
- API keys
- local databases
- `.venv`
- generated workspace artifacts

## 14. Change Discipline

When modifying existing behavior:

1. Explain the reason internally through code/comments/tests, not hidden assumptions.
2. Preserve existing working behavior unless the task requires otherwise.
3. Prefer the smallest change that solves the problem.
4. Update tests when behavior changes.
5. Update project documentation when architecture changes.

## 15. Dependency Discipline

Before adding a dependency, ask:

- Can the standard library solve this?
- Can an existing dependency solve it?
- Does this materially simplify AgentHQ?
- Does it introduce unnecessary infrastructure?

Record significant architectural dependencies in `ARCHITECTURE.md`.

## 16. AgentHQ Definition of Done

A feature is not complete merely because the UI renders.

It should have:

- backend behavior
- persistent state where applicable
- error handling
- tests
- UI state
- documentation when architecture is affected

## 17. Current Priority

Build in this order:

1. Project foundation
2. Database models
3. Agent abstraction
4. LLM provider abstraction
5. Manager planning
6. Task orchestration
7. Designer + Developer agents
8. QA/rework loop
9. Activity/event system
10. Filesystem/Git tools
11. Graphify
12. Sandboxed execution
13. PostgreSQL
14. Expanded workforce

Do not jump to later infrastructure before the earlier loop works.
