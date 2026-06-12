from datetime import UTC

import pytest

from eventbuddy.data.db import session_scope
from eventbuddy.data.repositories.events import EventRepository
from eventbuddy.data.repositories.members import MemberRepository
from eventbuddy.data.repositories.tasks import TaskRepository

pytestmark = pytest.mark.integration


def test_event_crud_and_lookup_by_channel():
    with session_scope() as s:
        repo = EventRepository(s)
        ev = repo.create(event_name="AI Workshop", host_user_id="u1", objective="learn")
        s.flush()
        assert repo.get(ev.event_id).event_name == "AI Workshop"
        repo.set_channel(ev.event_id, "ch-123")
        repo.set_status(ev.event_id, "planning")
        s.flush()
        assert repo.by_channel("ch-123").status == "planning"


def test_members_add_and_registration_rate():
    with session_scope() as s:
        ev = EventRepository(s).create(event_name="E", host_user_id="u1")
        s.flush()
        mrepo = MemberRepository(s)
        mrepo.add_many(ev.event_id, [
            {"email": "a@x.com", "teams_user_id": "ua", "role": "member"},
            {"email": "b@x.com", "teams_user_id": "ub", "role": "member"},
        ])
        s.flush()
        mrepo.set_registration(ev.event_id, "ua", "registered")
        s.flush()
        assert mrepo.registration_rate(ev.event_id) == 0.5
        assert {m.teams_user_id for m in mrepo.pending(ev.event_id)} == {"ub"}


def test_tasks_due_within_and_by_assignee():
    from datetime import datetime, timedelta
    with session_scope() as s:
        ev = EventRepository(s).create(event_name="E", host_user_id="u1")
        s.flush()
        trepo = TaskRepository(s)
        soon = datetime.now(UTC) + timedelta(hours=12)
        trepo.create(ev.event_id, "slides", assignee_id="ua", due_date=soon)
        s.flush()
        assert len(trepo.due_within(ev.event_id, hours=24)) == 1
        assert len(trepo.by_assignee("ua")) == 1
