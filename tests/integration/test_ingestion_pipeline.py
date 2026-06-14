import pytest

from eventbuddy.data.db import session_scope
from eventbuddy.data.repositories.events import EventRepository
from eventbuddy.data.repositories.members import MemberRepository
from eventbuddy.data.repositories.tasks import TaskRepository
from eventbuddy.ingestion.parsers import ParsedDoc
from eventbuddy.ingestion.pipeline import IngestionPipeline

pytestmark = pytest.mark.integration


class _Graph:
    def get_drive_item_content(self, drive_id, item_id):
        return (b"", "guests.xlsx", "application/xlsx")


class _Extractor:
    def structure(self, parsed):
        return {
            "members": [{"email": "new@x.com", "display_name": "New", "role": "member"}],
            "tasks": [{"task_name": "Book the room", "assignee_email": "new@x.com",
                       "due_date": None}],
        }


class _PendingStore:
    def __init__(self):
        self.payloads = []

    def put(self, payload):
        self.payloads.append(payload)
        return "pid-1"


def _seed_event_with_channel():
    with session_scope() as s:
        ev = EventRepository(s).create(
            event_name="Demo", host_user_id="host-1", teams_channel_id="chan-1")
        s.flush()
        return ev.event_id


def test_pipeline_upserts_members_tasks_and_proposes_invites():
    event_id = _seed_event_with_channel()
    posted = []
    store = _PendingStore()
    pipe = IngestionPipeline(
        _Graph(), _Extractor(), pending_store=store,
        post_card=lambda channel_id, card: posted.append((channel_id, card)),
        parse=lambda f, c: ParsedDoc(kind="xlsx", filename=f, text="rows"),
    )
    res = pipe.ingest(drive_id="drv1", item_id="item-1", event_id=event_id)

    assert res.documents == 1
    assert res.members_added == 1
    assert res.tasks_added == 1
    # the new member is pending → an invite is proposed and a card posted to the channel
    assert res.invited_proposed == 1
    assert posted and posted[0][0] == "chan-1"
    assert store.payloads[0]["type"] == "mail"
    assert store.payloads[0]["recipient_emails"] == ["new@x.com"]

    with session_scope() as s:
        assert {m.email for m in MemberRepository(s).list(event_id)} == {"new@x.com"}
        tasks = TaskRepository(s).list(event_id)
        assert tasks[0].task_name == "Book the room"
        assert tasks[0].source_document == "guests.xlsx"


def test_pipeline_skips_already_ingested_drive_item():
    event_id = _seed_event_with_channel()
    pipe = IngestionPipeline(
        _Graph(), _Extractor(), pending_store=_PendingStore(),
        post_card=lambda *a: None,
        parse=lambda f, c: ParsedDoc(kind="xlsx", filename=f, text="rows"),
    )
    first = pipe.ingest(drive_id="drv1", item_id="dup-1", event_id=event_id)
    second = pipe.ingest(drive_id="drv1", item_id="dup-1", event_id=event_id)
    assert first.documents == 1
    assert second.skipped == "already_ingested"
