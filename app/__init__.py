"""Flask application factory for AgentHQ."""

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request

from app.config import AppConfig
from app.llm.providers import build_provider_registry
from app.llm.router import LLMRouter
from app.models.database import Base, get_engine, get_session_factory, get_db
from app.routes.api import api_bp
from app.routes.ui import ui_bp

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DOTENV_PATH = _PROJECT_ROOT / ".env"


def _load_project_dotenv(path: Path | None = None) -> bool:
    """Load the project root ``.env`` into ``os.environ``.

    Existing environment variables always take precedence over values
    from the file (``override=False``).
    """
    return load_dotenv(dotenv_path=path or _DOTENV_PATH, override=False)


def create_app(config: dict | None = None) -> Flask:
    _load_project_dotenv()

    app_config = AppConfig(overrides=config)

    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["SECRET_KEY"] = app_config.secret_key
    app.config["DATABASE_URL"] = app_config.database_url

    if config:
        app.config.update(config)

    engine = get_engine(app.config["DATABASE_URL"])
    app.session_factory = get_session_factory(engine)
    Base.metadata.create_all(engine)

    @app.teardown_appcontext
    def close_db(exc=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    provider_registry = build_provider_registry()
    llm_router = LLMRouter(
        role_configs=app_config.llm_role_configs,
        provider_registry=provider_registry,
    )

    from app.agents import build_registry
    build_registry(llm_router, app_config)

    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(ui_bp)

    _register_error_handlers(app)

    return app


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(400)
    def bad_request(e):
        if request.path.startswith("/api"):
            return jsonify({"error": str(e), "code": "bad_request"}), 400
        return render_template("error.html", code=400, message="Bad request"), 400

    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith("/api"):
            return jsonify({"error": str(e), "code": "not_found"}), 404
        return render_template("error.html", code=404, message="Page not found"), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        if request.path.startswith("/api"):
            return jsonify({"error": str(e), "code": "method_not_allowed"}), 405
        return render_template("error.html", code=405, message="Method not allowed"), 405

    @app.errorhandler(422)
    def unprocessable(e):
        return jsonify({"error": str(e), "code": "validation_error"}), 422

    @app.errorhandler(500)
    def internal_error(e):
        if request.path.startswith("/api"):
            return jsonify({"error": "An internal error occurred.", "code": "internal_error"}), 500
        return render_template("error.html", code=500, message="Internal error"), 500
