"""Route blueprints."""

from app.routes.api import api_bp
from app.routes.ui import ui_bp

__all__ = ["api_bp", "ui_bp"]
