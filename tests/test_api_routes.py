"""HTTP contract tests for API and UI routes."""

import logging
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.agents.manager import ManagerAgent
from app.constants import AgentRole, ProjectStatus, TaskPriority, TaskStatus
from app.exceptions import ConflictError, InvalidTransitionError, LLMProviderError
from app.schemas import ModelConfig
from app import create_app


@pytest.fixture()
def app():
    application = create_app(config={
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "DATABASE_URL": "sqlite:///:memory:",
        "AGENT_MANAGER_MODEL": "gpt-4o-mini",
        "AGENT_MANAGER_PROVIDER": "openai",
    })
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def mock_router():
    router = MagicMock()
    router.complete.return_value = """{
      "tasks": [
        {"local_id": "TASK-1", "title": "Build", "description": "Do it", "assigned_role": "backend", "priority": "high", "dependencies": []}
      ]
    }"""
    return router


@pytest.fixture()
def manager_agent(mock_router):
    return ManagerAgent(mock_router, ModelConfig(provider="openai", model="gpt-4o-mini"))


@pytest.fixture()
def project_id(client):
    resp = client.post("/api/projects", json={"title": "Test", "description": "Desc"})
    assert resp.status_code == 201
    return resp.get_json()["project"]["id"]


class TestApiRoutes:
    def test_create_project_returns_201_and_project(self, client):
        resp = client.post("/api/projects", json={"title": "Alpha", "description": "Build alpha"})
        assert resp.status_code == 201
        assert resp.content_type == "application/json"
        data = resp.get_json()
        assert "project" in data
        assert data["project"]["title"] == "Alpha"
        assert data["project"]["status"] == "draft"

    def test_create_project_validation_errors_return_422(self, client):
        resp = client.post("/api/projects", json={"title": "", "description": "Desc"})
        assert resp.status_code == 422
        assert resp.get_json()["code"] == "validation_error"

        resp = client.post("/api/projects", json={"title": "A" * 201, "description": "Desc"})
        assert resp.status_code == 422

        resp = client.post("/api/projects", json={"title": "A", "description": ""})
        assert resp.status_code == 422

    def test_list_projects_returns_200(self, client, project_id):
        resp = client.get("/api/projects")
        assert resp.status_code == 200
        assert resp.content_type == "application/json"
        data = resp.get_json()
        assert "projects" in data
        assert len(data["projects"]) >= 1

    def test_get_project_returns_200(self, client, project_id):
        resp = client.get(f"/api/projects/{project_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["project"]["id"] == project_id

    def test_get_project_invalid_uuid_returns_400(self, client):
        resp = client.get("/api/projects/not-a-uuid")
        assert resp.status_code == 400

    def test_get_project_missing_returns_404(self, client):
        resp = client.get("/api/projects/12345678-1234-4123-8123-123456789012")
        assert resp.status_code == 404
        assert resp.get_json()["code"] == "not_found"

    def test_update_project_status_invalid_returns_422(self, client, project_id):
        resp = client.patch(f"/api/projects/{project_id}/status", json={"status": "not_a_status"})
        assert resp.status_code == 422

    def test_update_project_status_valid_returns_200(self, client, project_id):
        resp = client.patch(f"/api/projects/{project_id}/status", json={"status": "planning"})
        assert resp.status_code == 200
        assert resp.get_json()["project"]["status"] == "planning"

    def test_update_project_status_invalid_transition_returns_422(self, client, project_id):
        client.patch(f"/api/projects/{project_id}/status", json={"status": "planning"})
        resp = client.patch(f"/api/projects/{project_id}/status", json={"status": "delivered"})
        assert resp.status_code == 422
        assert resp.get_json()["code"] == "invalid_transition"

    def test_list_tasks_returns_200(self, client, project_id):
        resp = client.get(f"/api/projects/{project_id}/tasks")
        assert resp.status_code == 200
        assert "tasks" in resp.get_json()

    def test_get_task_returns_200_with_dependency_ids(self, client, project_id):
        resp = client.get(f"/api/projects/{project_id}/tasks")
        assert resp.status_code == 200
        tasks = resp.get_json()["tasks"]
        if tasks:
            task_id = tasks[0]["id"]
            resp = client.get(f"/api/projects/{project_id}/tasks/{task_id}")
            assert resp.status_code == 200
            data = resp.get_json()["task"]
            assert "prerequisite_ids" in data
            assert "dependent_ids" in data

    def test_get_task_invalid_uuid_returns_400(self, client, project_id):
        resp = client.get(f"/api/projects/{project_id}/tasks/not-a-uuid")
        assert resp.status_code == 400

    def test_update_task_status_valid_transition_returns_200(self, client, project_id):
        resp = client.get(f"/api/projects/{project_id}/tasks")
        assert resp.status_code == 200
        tasks = resp.get_json()["tasks"]
        if tasks:
            task_id = tasks[0]["id"]
            resp = client.patch(
                f"/api/projects/{project_id}/tasks/{task_id}/status",
                json={"status": "in_progress"},
            )
            assert resp.status_code == 200
            assert resp.get_json()["task"]["status"] == "in_progress"

    def test_update_task_status_invalid_transition_returns_422(self, client, project_id):
        resp = client.get(f"/api/projects/{project_id}/tasks")
        assert resp.status_code == 200
        tasks = resp.get_json()["tasks"]
        if tasks:
            task_id = tasks[0]["id"]
            resp = client.patch(
                f"/api/projects/{project_id}/tasks/{task_id}/status",
                json={"status": "done"},
            )
            assert resp.status_code == 422
            assert resp.get_json()["code"] == "invalid_transition"

    def test_get_task_dependencies_returns_200(self, client, project_id):
        resp = client.get(f"/api/projects/{project_id}/tasks")
        assert resp.status_code == 200
        tasks = resp.get_json()["tasks"]
        if tasks:
            task_id = tasks[0]["id"]
            resp = client.get(f"/api/projects/{project_id}/tasks/{task_id}/dependencies")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "prerequisites" in data
            assert "dependents" in data

    def test_get_events_returns_200(self, client, project_id):
        resp = client.get(f"/api/projects/{project_id}/events")
        assert resp.status_code == 200
        assert "events" in resp.get_json()

    def test_get_events_invalid_project_returns_404(self, client):
        resp = client.get("/api/projects/12345678-1234-4123-8123-123456789012/events")
        assert resp.status_code == 404

    def test_trigger_planning_returns_200(self, client, project_id, monkeypatch):
        mock_router = MagicMock()
        mock_router.complete.return_value = """{
          "tasks": [
            {"local_id": "TASK-1", "title": "Task", "description": "D", "assigned_role": "backend", "priority": "high", "dependencies": []}
          ]
        }"""
        from app.agents import AGENT_REGISTRY
        original = AGENT_REGISTRY.get(AgentRole.manager)
        AGENT_REGISTRY[AgentRole.manager] = ManagerAgent(mock_router, ModelConfig(provider="o", model="m"))
        try:
            resp = client.post(f"/api/projects/{project_id}/plan")
            assert resp.status_code == 200
            assert resp.get_json()["status"] == "planning_triggered"
        finally:
            AGENT_REGISTRY[AgentRole.manager] = original

    def test_trigger_planning_conflict_returns_409(self, client, project_id):
        client.patch(f"/api/projects/{project_id}/status", json={"status": "planning"})
        resp = client.post(f"/api/projects/{project_id}/plan")
        assert resp.status_code == 409
        assert resp.get_json()["code"] == "conflict"

    def test_trigger_planning_invalid_uuid_returns_400(self, client):
        resp = client.post("/api/projects/not-a-uuid/plan")
        assert resp.status_code == 400

    def test_trigger_planning_unexpected_exception_returns_generic_500(
        self, client, project_id, caplog
    ):
        from app.agents import AGENT_REGISTRY

        class BoomRouter:
            def complete(self, *args, **kwargs):
                raise RuntimeError("provider boom")

        original = AGENT_REGISTRY.get(AgentRole.manager)
        AGENT_REGISTRY[AgentRole.manager] = ManagerAgent(
            BoomRouter(), ModelConfig(provider="o", model="m")
        )
        try:
            with caplog.at_level(logging.ERROR, logger="agenthq.routes"):
                resp = client.post(f"/api/projects/{project_id}/plan")
            assert resp.status_code == 500
            assert resp.get_json() == {
                "code": "internal_error",
                "error": "An internal error occurred.",
            }
            assert any(
                "trigger_planning failed" in rec.message
                and rec.exc_info is not None
                and isinstance(rec.exc_info[1], RuntimeError)
                for rec in caplog.records
            )
        finally:
            AGENT_REGISTRY[AgentRole.manager] = original


class TestUiRoutes:
    def test_dashboard_returns_html(self, client, project_id):
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.content_type == "text/html; charset=utf-8"
        assert b"Projects" in resp.data

    def test_project_form_returns_html(self, client):
        resp = client.get("/projects/new")
        assert resp.status_code == 200
        assert resp.content_type == "text/html; charset=utf-8"
        assert b"New Project" in resp.data

    def test_project_detail_returns_html(self, client, project_id):
        resp = client.get(f"/projects/{project_id}")
        assert resp.status_code == 200
        assert resp.content_type == "text/html; charset=utf-8"
        assert b"Tasks" in resp.data

    def test_project_detail_invalid_uuid_returns_400(self, client):
        resp = client.get("/projects/not-a-uuid")
        assert resp.status_code == 400

    def test_project_detail_not_found_returns_404(self, client):
        resp = client.get("/projects/12345678-1234-4123-8123-123456789012")
        assert resp.status_code == 404
