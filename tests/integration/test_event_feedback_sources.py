import pytest

from eventbuddy.data.db import session_scope
from eventbuddy.data.repositories.events import EventRepository

pytestmark = pytest.mark.integration


def test_set_feedback_sources_persists_and_is_partial():
    with session_scope() as s:
        repo = EventRepository(s)
        ev = repo.create(event_name="E", host_user_id="u1")
        s.flush()
        eid = ev.event_id

        repo.set_feedback_sources(eid, form_url="https://forms/r/abc")
        s.flush()
        assert repo.get(eid).feedback_form_url == "https://forms/r/abc"
        assert repo.get(eid).feedback_workbook_url is None

        # setting only the workbook must not clobber the previously-set form link
        repo.set_feedback_sources(eid, workbook_url="https://share/wb.xlsx")
        s.flush()
        assert repo.get(eid).feedback_form_url == "https://forms/r/abc"
        assert repo.get(eid).feedback_workbook_url == "https://share/wb.xlsx"
