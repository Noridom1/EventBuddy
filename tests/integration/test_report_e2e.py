import pytest

from eventbuddy.capabilities.reporting import ReportingService
from eventbuddy.data.db import session_scope
from eventbuddy.data.repositories.events import EventRepository
from eventbuddy.data.repositories.feedback import FeedbackRepository
from eventbuddy.data.repositories.members import MemberRepository
from eventbuddy.data.repositories.reports import ReportRepository

pytestmark = pytest.mark.integration


class _StubLLM:
    def summarize(self, text, instruction):
        return "85% satisfied; content praised."

    def chat(self, messages, model=None):
        return "1. Shorten sessions to 90 min."


def test_full_report_pipeline_persists_report():
    with session_scope() as s:
        ev = EventRepository(s).create(event_name="E", host_user_id="u1")
        s.flush()
        MemberRepository(s).add_many(ev.event_id, [
            {"email": "a@x.com", "teams_user_id": "ua", "role": "member"},
            {"email": "b@x.com", "teams_user_id": "ub", "role": "member"},
        ])
        s.flush()
        MemberRepository(s).set_registration(ev.event_id, "ua", "registered")
        FeedbackRepository(s).add(ev.event_id, respondent_id="ua",
                                  raw_payload={"rating": 5, "comment": "great"},
                                  sentiment="positive", themes={"tags": ["content"]})
        s.flush()
        report = ReportingService(MemberRepository(s), FeedbackRepository(s),
                                  ReportRepository(s), _StubLLM()).generate(event_id=ev.event_id)
        s.flush()
        assert report.metrics_json["registration_rate"] == 0.5
        assert report.metrics_json["response_rate"] == 0.5
        assert ReportRepository(s).latest(ev.event_id).suggestions_md.startswith("1.")
