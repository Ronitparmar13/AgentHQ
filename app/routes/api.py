"""REST API blueprint."""

from sqlalchemy.orm import Session

from flask import Blueprint, jsonify, request

from app.agents import AGENT_REGISTRY
from app.constants import AgentRole
from app.exceptions import ConflictError, InvalidTransitionError, NotFoundError
from app.routes.helpers import json_error, validate_uuid4
from app.schemas import (
    CreateProjectRequest,
    UpdateProjectStatusRequest,
    UpdateTaskStatusRequest,
)
from app.services import EventService, ProjectService, TaskService

api_bp = Blueprint("api", __name__)


def _get_session() -> Session:
    from app.models.database import get_db
    return get_db()


def _project_service() -> ProjectService:
    return ProjectService()


def _task_service() -> TaskService:
    return TaskService()


def _event_service() -> EventService:
    return EventService()


@api_bp.route("/projects", methods=["POST"])
def create_project():
    session = _get_session()
    try:
        payload = CreateProjectRequest.model_validate(request.get_json() or {})
    except Exception as exc:
        return json_error(str(exc), "validation_error", 422)

    try:
        project = _project_service().create_project(
            session, payload.title, payload.description
        )
        session.commit()
    except ValueError as exc:
        return json_error(str(exc), "validation_error", 422)
    except Exception:
        session.rollback()
        return json_error("An internal error occurred.", "internal_error", 500)

    return jsonify({"project": project.to_dict()}), 201


@api_bp.route("/projects", methods=["GET"])
def list_projects():
    session = _get_session()
    projects = _project_service().list_projects(session)
    return jsonify({"projects": [p.to_dict() for p in projects]}), 200


@api_bp.route("/projects/<project_id>", methods=["GET"])
def get_project(project_id: str):
    try:
        validate_uuid4(project_id, "project_id")
    except ValueError as exc:
        return json_error(str(exc), "bad_request", 400)

    session = _get_session()
    try:
        project = _project_service().get_project(session, project_id)
    except NotFoundError as exc:
        return json_error(str(exc), "not_found", 404)
    return jsonify({"project": project.to_dict()}), 200


@api_bp.route("/projects/<project_id>/status", methods=["PATCH"])
def update_project_status(project_id: str):
    try:
        validate_uuid4(project_id, "project_id")
    except ValueError as exc:
        return json_error(str(exc), "bad_request", 400)

    session = _get_session()
    try:
        payload = UpdateProjectStatusRequest.model_validate(request.get_json() or {})
    except Exception as exc:
        return json_error(str(exc), "validation_error", 422)

    try:
        project = _project_service().update_project_status(
            session, project_id, payload.status
        )
        session.commit()
    except NotFoundError as exc:
        return json_error(str(exc), "not_found", 404)
    except InvalidTransitionError as exc:
        return json_error(
            str(exc), "invalid_transition", 422,
            current_status=exc.current, target_status=exc.target,
        )
    except ValueError as exc:
        return json_error(str(exc), "validation_error", 422)
    except Exception:
        session.rollback()
        return json_error("An internal error occurred.", "internal_error", 500)

    return jsonify({"project": project.to_dict()}), 200


@api_bp.route("/projects/<project_id>/tasks", methods=["GET"])
def list_tasks(project_id: str):
    try:
        validate_uuid4(project_id, "project_id")
    except ValueError as exc:
        return json_error(str(exc), "bad_request", 400)

    session = _get_session()
    try:
        tasks = _task_service().list_tasks(session, project_id)
    except NotFoundError as exc:
        return json_error(str(exc), "not_found", 404)
    return jsonify({"tasks": [t.to_dict() for t in tasks]}), 200


@api_bp.route("/projects/<project_id>/tasks/<task_id>", methods=["GET"])
def get_task(project_id: str, task_id: str):
    try:
        validate_uuid4(project_id, "project_id")
        validate_uuid4(task_id, "task_id")
    except ValueError as exc:
        return json_error(str(exc), "bad_request", 400)

    session = _get_session()
    try:
        task = _task_service().get_task(session, project_id, task_id)
    except NotFoundError as exc:
        return json_error(str(exc), "not_found", 404)

    deps = _task_service().get_task_dependencies(session, project_id, task_id)
    data = task.to_dict()
    data["prerequisite_ids"] = [d["id"] for d in deps["prerequisites"]]
    data["dependent_ids"] = [d["id"] for d in deps["dependents"]]
    return jsonify({"task": data}), 200


@api_bp.route("/projects/<project_id>/tasks/<task_id>/status", methods=["PATCH"])
def update_task_status(project_id: str, task_id: str):
    try:
        validate_uuid4(project_id, "project_id")
        validate_uuid4(task_id, "task_id")
    except ValueError as exc:
        return json_error(str(exc), "bad_request", 400)

    try:
        payload = UpdateTaskStatusRequest.model_validate(request.get_json() or {})
    except Exception as exc:
        return json_error(str(exc), "validation_error", 422)

    session = _get_session()
    try:
        task = _task_service().update_task_status(
            session, project_id, task_id, payload.status
        )
        session.commit()
    except NotFoundError as exc:
        return json_error(str(exc), "not_found", 404)
    except InvalidTransitionError as exc:
        return json_error(
            str(exc), "invalid_transition", 422,
            current_status=exc.current, target_status=exc.target,
        )
    except ValueError as exc:
        return json_error(str(exc), "validation_error", 422)
    except Exception:
        session.rollback()
        return json_error("An internal error occurred.", "internal_error", 500)

    return jsonify({"task": task.to_dict()}), 200


@api_bp.route("/projects/<project_id>/tasks/<task_id>/dependencies", methods=["GET"])
def get_task_dependencies(project_id: str, task_id: str):
    try:
        validate_uuid4(project_id, "project_id")
        validate_uuid4(task_id, "task_id")
    except ValueError as exc:
        return json_error(str(exc), "bad_request", 400)

    session = _get_session()
    try:
        deps = _task_service().get_task_dependencies(session, project_id, task_id)
    except NotFoundError as exc:
        return json_error(str(exc), "not_found", 404)
    return jsonify(deps), 200


@api_bp.route("/projects/<project_id>/events", methods=["GET"])
def list_events(project_id: str):
    try:
        validate_uuid4(project_id, "project_id")
    except ValueError as exc:
        return json_error(str(exc), "bad_request", 400)

    session = _get_session()
    try:
        _project_service().get_project(session, project_id)
    except NotFoundError as exc:
        return json_error(str(exc), "not_found", 404)

    events = _event_service().list_events(session, project_id)
    return jsonify({"events": [e.to_dict() for e in events]}), 200


@api_bp.route("/projects/<project_id>/plan", methods=["POST"])
def trigger_planning(project_id: str):
    try:
        validate_uuid4(project_id, "project_id")
    except ValueError as exc:
        return json_error(str(exc), "bad_request", 400)

    session = _get_session()
    manager = AGENT_REGISTRY.get(AgentRole.manager)
    if manager is None:
        return json_error("Manager agent is not configured.", "internal_error", 500)

    try:
        _project_service().trigger_planning(session, project_id, manager)
        session.commit()
    except NotFoundError as exc:
        return json_error(str(exc), "not_found", 404)
    except InvalidTransitionError as exc:
        return json_error(
            str(exc), "invalid_transition", 422,
            current_status=exc.current, target_status=exc.target,
        )
    except ConflictError as exc:
        return json_error(str(exc), "conflict", 409)
    except ValueError as exc:
        return json_error(str(exc), "validation_error", 422)
    except Exception:
        session.rollback()
        return json_error("An internal error occurred.", "internal_error", 500)

    return jsonify({"status": "planning_triggered"}), 200
