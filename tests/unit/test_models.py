# tests/unit/test_models.py
from eventbuddy.domain.models import Event, EventMember, Task


def test_event_tablename_and_columns():
    assert Event.__tablename__ == "events"
    cols = set(Event.__table__.columns.keys())
    assert {"event_id", "event_name", "teams_channel_id", "status"} <= cols


def test_member_has_event_fk_and_unique():
    cols = set(EventMember.__table__.columns.keys())
    assert {"event_id", "teams_user_id", "role", "registration_status"} <= cols


def test_task_has_event_fk_and_status():
    cols = set(Task.__table__.columns.keys())
    assert {"event_id", "task_name", "assignee_id", "due_date", "status"} <= cols
