"""Plain SQLAlchemy 2.x database primitives."""

from collections.abc import Callable

from flask import current_app, g
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all AgentHQ persistence models."""


def get_engine(database_url: str | URL) -> Engine:
    """Create an engine with SQLite foreign-key enforcement enabled."""
    engine = create_engine(database_url)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Session:
    """Return the lazily-created request-scoped session from ``flask.g``."""
    if "db" not in g:
        factory: Callable[[], Session] = current_app.session_factory
        g.db = factory()
    return g.db
