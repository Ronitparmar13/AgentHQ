# AgentHQ

> **One HQ. An entire AI team.**

AgentHQ is an experimental autonomous AI software company presented as a virtual office.

A CEO gives a software project to a Manager Agent. The Manager plans the work, delegates tasks to specialist AI employees, coordinates dependencies, handles QA feedback, and drives the project toward completion.

## Team

| Agent | Responsibility |
|---|---|
| Manager | Planning, delegation, review, coordination |
| UI/UX Designer | Flows, design specifications, UX |
| Frontend Developer | UI implementation |
| Backend Developer | APIs, persistence, business logic |
| QA Engineer | Testing, defects, verification |
| HR Analyst | Workforce and workload support |
| Utility Agent | Bounded support tasks |

## Core Workflow

```text
CEO
 |
 v
Manager
 |
 +--> Designer
 +--> Frontend
 +--> Backend
 |
 v
QA
 |
 +--> PASS ---> Manager ---> Delivery
 |
 +--> FAIL ---> Developer ---> QA
```

## Initial Stack

- Python 3.12
- Flask
- Jinja2
- HTML/CSS/JavaScript
- SQLAlchemy
- SQLite
- Custom Python agent runtime
- Graphify
- Git

PostgreSQL and containerized execution are planned later.

## Project Structure

```text
app/
├── agents/
├── llm/
├── models/
├── orchestration/
├── routes/
├── services/
└── tools/

templates/
static/
tests/
workspace/
```

## Development Philosophy

AgentHQ deliberately starts as a modular monolith.

The goal is to make one real end-to-end agent workflow reliable before adding advanced infrastructure.

The project uses separate layers for:

- agent reasoning
- tools and side effects
- orchestration
- persistent state
- repository/code intelligence
- presentation

## Security

Never commit API keys.

Use `.env` locally and `.env.example` as a template.

Autonomous command execution must remain restricted and should move to disposable sandbox containers before allowing untrusted generated code to execute.

## Status

Early development.

The current target is the first working Manager → Specialist → QA → Rework → Approval loop.
