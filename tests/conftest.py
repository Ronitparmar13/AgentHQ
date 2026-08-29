import pytest
from sqlalchemy.orm import Session

from app.models import Base, get_engine, get_session_factory


@pytest.fixture
def session() -> Session:
    engine = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    db_session = factory()
    try:
        yield db_session
    finally:
        db_session.close()
        engine.dispose()
