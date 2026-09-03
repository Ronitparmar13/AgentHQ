"""UI routes blueprint."""

from flask import Blueprint, render_template

from app.routes.helpers import validate_uuid4
from app.services import ProjectService, TaskService

ui_bp = Blueprint("ui", __name__)


@ui_bp.route("/")
def dashboard():
    service = ProjectService()
    from app.models.database import get_db
    session = get_db()
    projects = service.list_projects(session)
    return render_template("dashboard.html", projects=projects)


@ui_bp.route("/projects/new")
def project_form():
    return render_template("project_form.html")


@ui_bp.route("/projects/<project_id>")
def project_detail(project_id: str):
    try:
        validate_uuid4(project_id, "project_id")
    except ValueError:
        return render_template("error.html", code=400, message="Invalid project identifier."), 400

    project_service = ProjectService()
    task_service = TaskService()
    from app.models.database import get_db
    session = get_db()
    try:
        project = project_service.get_project(session, project_id)
    except Exception:
        return render_template("error.html", code=404, message="Project not found."), 404

    tasks = task_service.list_tasks(session, project_id)
    from app.services import EventService
    events = EventService().list_events(session, project_id)
    event_dicts = [e.to_dict() for e in events]
    return render_template(
        "project_detail.html", project=project, tasks=tasks, events=event_dicts
    )
