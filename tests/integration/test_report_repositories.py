import pytest

from eventbuddy.data.db import session_scope
from eventbuddy.data.repositories.events import EventRepository
from eventbuddy.data.repositories.feedback import FeedbackRepository
from eventbuddy.data.repositories.reports import ReportRepository

pytestmark = pytest.mark.integration


def test_feedback_add_list_and_respondent_emails():
    with session_scope() as s:
        ev = EventRepository(s).create(event_name="E", host_user_id="u1")
        s.flush()
        frepo = FeedbackRepository(s)
        frepo.add(ev.event_id, respondent_id="a@x.com",
                  raw_payload={"rating": 5, "comment": "great", "email": "a@x.com"})
        frepo.add(ev.event_id, respondent_id="ub",
                  raw_payload={"rating": 3, "comment": "long"})
        s.flush()
        assert len(frepo.list(ev.event_id)) == 2
        assert frepo.respondent_emails(ev.event_id) == {"a@x.com"}
        assert "a@x.com" in frepo.respondent_ids(ev.event_id)


def test_report_create_and_latest():
    with session_scope() as s:
        ev = EventRepository(s).create(event_name="E", host_user_id="u1")
        s.flush()
        rrepo = ReportRepository(s)
        rrepo.create(ev.event_id, metrics_json={"response_rate": 0.5},
                     summary_md="ok", suggestions_md="do X")
        s.flush()
        assert rrepo.latest(ev.event_id).summary_md == "ok"
