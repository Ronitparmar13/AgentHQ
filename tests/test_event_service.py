from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import Event, Project
from app.services.event_service import EventService


def make_project(session: Session) -> Project:
    project = Project(title="Project", description="Description")
    session.add(project)
    session.commit()
    return project


def test_event_service_records_and_lists_events_in_order(session: Session) -> None:
    project = make_project(session)
    service = EventService()
    first = service.record(session, project.id, "first", {"value": 1})
    second = service.record(session, project.id, "second", {"value": 2})
    second.created_at = first.created_at + timedelta(seconds=1)
    session.commit()

    assert [event.event_name for event in service.list_events(session, project.id)] == ["first", "second"]


def test_event_redaction_is_recursive_through_depth_three_and_non_destructive(session: Session) -> None:
    project = make_project(session)
    payload = {
        "api_key": "top",
        "level_one": {
            "token": "second",
            "level_two": {"secret": "third", "level_three": {"password": "fourth"}},
        },
    }
    original = payload["level_one"]["level_two"]["level_three"]["password"]
    event = EventService().record(session, project.id, "safe", payload)

    assert event.payload_dict["api_key"] == "[REDACTED]"
    assert event.payload_dict["level_one"]["token"] == "[REDACTED]"
    assert event.payload_dict["level_one"]["level_two"]["secret"] == "[REDACTED]"
    assert event.payload_dict["level_one"]["level_two"]["level_three"]["password"] == "fourth"
    assert original == "fourth"
