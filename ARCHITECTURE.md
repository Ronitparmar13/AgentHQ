# AgentHQ Architecture

## 1. Architecture Goal

Build a modular monolithic application first.

The initial system should be easy to run locally, easy to debug, and easy to evolve.

Primary stack:

- Python 3.12
- Flask
- Jinja2
- HTML/CSS/JavaScript
- SQLAlchemy
- SQLite for MVP
- PostgreSQL later
- Custom Python agent runtime
- Graphify for repository/code intelligence
- Git for source control
- Controlled workspace for agent artifacts/code
- Docker sandbox later for untrusted code execution

## 2. High-Level System

```text
                         CEO / User
                             |
                             v
                     +----------------+
                     |   Flask Web    |
                     | UI + REST/API  |
                     +--------+-------+
                              |
                              v
                    +---------------------+
                    | Agent Orchestrator  |
                    +----------+----------+
                               |
             +-----------------+------------------+
             |                 |                  |
             v                 v                  v
          Manager          Task System       Event System
             |
       +-----+------+------+ 
       |            |      |
       v            v      v
   Designer      Frontend Backend
       |            |      |
       +------------+------+
                    |
                    v
                    QA
                    |
             PASS / REWORK
                    |
                    v
                 Manager

       Shared infrastructure underneath:
       ----------------------------------
       Database
       Project workspace
       Git
       Graphify
       LLM provider layer
       Tool layer
```

## 3. Repository Structure

```text
AgentHQ/
├── PROJECT.md
├── ARCHITECTURE.md
├── AGENTS.md
├── README.md
├── .env.example
├── .gitignore
├── pyproject.toml
│
├── app/
│   ├── __init__.py
│   ├── agents/
│   │   ├── base.py
│   │   ├── manager.py
│   │   ├── designer.py
│   │   ├── frontend.py
│   │   ├── backend.py
│   │   ├── qa.py
│   │   ├── hr.py
│   │   └── utility.py
│   │
│   ├── llm/
│   │   ├── base.py
│   │   ├── router.py
│   │   ├── providers/
│   │   └── config.py
│   │
│   ├── models/
│   ├── orchestration/
│   ├── routes/
│   ├── services/
│   └── tools/
│       ├── filesystem.py
│       ├── git.py
│       ├── graphify.py
│       ├── testing.py
│       └── command.py
│
├── templates/
├── static/
│   ├── css/
│   ├── js/
│   └── assets/
│
├── tests/
├── docs/
└── workspace/
```

## 4. Agent Abstraction

All agents should use a common interface.

Conceptually:

```python
class BaseAgent:
    name: str
    role: str
    model: str

    async def run(self, task, context):
        ...
```

Agents should not directly manage Flask routes or database sessions.

Responsibilities are separated:

- Agent = reasoning + decisions
- Tool = side effects
- Service/orchestrator = workflow/state transitions
- Model = persistence
- Route = HTTP/UI boundary

## 5. LLM Provider Abstraction

The application should expose one internal interface:

```text
Agent
  |
  v
LLM Router
  |
  +--> Provider A
  +--> Provider B
  +--> Provider C
```

Model configuration belongs outside agent implementation.

Example configuration concept:

```text
AGENT_MANAGER_MODEL=...
AGENT_DESIGNER_MODEL=...
AGENT_FRONTEND_MODEL=...
AGENT_BACKEND_MODEL=...
AGENT_QA_MODEL=...
```

Exact provider/model identifiers are deployment configuration, not business logic.

The router should eventually support:

- retries
- provider failures
- fallback models
- timeout handling
- token/cost logging
- structured output validation

## 6. Task Orchestration

The Manager does not directly execute all work.

It creates structured tasks:

```json
{
  "title": "Implement dashboard",
  "assigned_role": "frontend",
  "priority": "high",
  "dependencies": ["DESIGN-001", "API-002"],
  "acceptance_criteria": [
    "Responsive layout",
    "Uses approved design",
    "Build passes"
  ]
}
```

The orchestrator persists the task and determines when it is eligible to run.

Dependencies must be explicit in the database.

## 7. Event System

Every important transition creates an event.

Example:

```text
project.created
task.created
task.assigned
task.started
task.completed
review.requested
bug.created
bug.fixed
qa.passed
qa.failed
project.delivered
```

Events feed:

- activity UI
- audit history
- agent context
- debugging
- future real-time updates

For MVP, events can be stored in SQLite and delivered through ordinary polling or Server-Sent Events. Do not introduce Kafka or a message broker initially.

## 8. Database

### MVP
SQLite + SQLAlchemy.

Suggested entities:

```text
Project
Agent
Task
TaskDependency
Message
Decision
Artifact
ProjectFile
TestRun
Defect
Event
```

### Later
PostgreSQL can replace SQLite while preserving the SQLAlchemy model layer.

Avoid database-specific assumptions in business logic.

## 9. Tool Layer

Tools are explicit, permissioned capabilities.

Initial tools:

### Filesystem
- list files
- read file
- write file
- search files

### Git
- status
- diff
- branch
- add
- commit
- log

### Testing
- run project tests
- run build
- capture stdout/stderr
- return structured result

### Graphify
- query project knowledge
- explain a node/concept
- trace relationships
- inspect relevant project structure

### Command execution
Use a strict allowlist initially.

Never expose unrestricted host shell access to an autonomous agent.

## 10. Graphify Integration

Graphify is the project/code intelligence layer.

Expected flow:

```text
Developer / QA Agent
        |
        v
 Graphify Tool
        |
        v
Repository knowledge graph
        |
        v
Relevant files/concepts/relationships
```

Use Graphify to reduce unnecessary repository-wide context loading and to help agents understand existing code.

Do not use Graphify to store:

- task status
- agent status
- workflow state
- user identity
- approvals

Those belong in the operational database.

## 11. Workspace Model

Each project receives an isolated workspace:

```text
workspace/
└── <project-id>/
    ├── source files
    ├── generated artifacts
    └── test output
```

Git should operate inside the project workspace/repository.

Later, code execution should happen inside a disposable container associated with the project.

## 12. Security

Minimum requirements:

- `.env` for secrets
- `.env` ignored by Git
- no hard-coded API keys
- validate all tool arguments
- restrict filesystem paths to the active project
- allowlist commands
- log tool calls
- separate user input from system instructions
- require explicit approval for destructive/high-impact operations
- never expose hidden model reasoning to the UI

## 13. Real-Time UI

MVP options:

1. Simple polling for activity.
2. Server-Sent Events for live activity.

Start with polling if it is materially simpler.

Upgrade to SSE when real-time behavior improves the experience.

WebSockets are not required for the initial version.

## 14. Recommended Execution Loop

```text
1. User creates project
2. Flask stores project
3. Orchestrator starts Manager
4. Manager creates plan
5. Orchestrator persists tasks
6. Eligible specialist tasks are dispatched
7. Agents use tools and produce artifacts
8. Agents emit events/messages
9. QA validates work
10. Defects create rework tasks
11. Developers repair
12. QA verifies
13. Manager performs final review
14. Orchestrator marks project delivered
```

## 15. Failure Handling

Every agent execution should be treated as potentially failing.

Capture:

- execution id
- agent
- task
- model
- start/end time
- status
- error category
- safe error message
- produced artifacts

Retry policies belong in the orchestrator, not inside individual UI routes.

## 16. Architectural Rules

- Prefer a modular monolith.
- Prefer simple Python abstractions over frameworks until complexity justifies them.
- Keep agents stateless between runs; persist required state in the database.
- Never let an LLM directly mutate database state without validated application code.
- Validate all structured LLM output with Pydantic.
- Keep side effects behind tools/services.
- Keep model selection configurable.
- Keep Graphify replaceable.
- Keep SQLite → PostgreSQL migration straightforward.
- Add infrastructure only when a demonstrated requirement exists.
