import pytest

from eventbuddy.data.db import session_scope
from eventbuddy.data.repositories.documents import DocumentRepository
from eventbuddy.data.repositories.events import EventRepository

pytestmark = pytest.mark.integration


def test_upsert_is_idempotent_by_drive_item():
    with session_scope() as s:
        ev = EventRepository(s).create(event_name="E", host_user_id="u1")
        s.flush()
        repo = DocumentRepository(s)
        doc1, created1 = repo.upsert(ev.event_id, filename="guests.xlsx", drive_item_id="item-1")
        s.flush()
        assert created1 is True
        doc2, created2 = repo.upsert(ev.event_id, filename="guests.xlsx", drive_item_id="item-1")
        assert created2 is False
        assert doc2.doc_id == doc1.doc_id
        assert repo.get_by_drive_item("item-1") is not None
        assert repo.get_by_drive_item("missing") is None
