"""Impl 5, Part 2 — the generic pipeline: understand + catalog, with member/task extraction
and invite-proposal DEMOTED to an optional roster/planning consumer.

A template/agenda/etc. is catalogued (summary + doc_type) with NO member/task/invite side
effects; only a roster/planning doc_type triggers the legacy extraction + invite card.
`session_scope` is sqlite-redirected (same pattern as test_brainstorm.py)."""
import contextlib

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from eventbuddy.data.repositories.documents import DocumentRepository
from eventbuddy.data.repositories.members import MemberRepository
from eventbuddy.domain.models import Document, Event, EventMember, Task
from eventbuddy.ingestion.parsers import ParsedDoc
from eventbuddy.ingestion.pipeline import IngestionPipeline


def _factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    for model in (Event, EventMember, Task, Document):
        model.__table__.create(engine)
    Local = sessionmaker(bind=engine, expire_on_commit=False)
    with Local() as s:
        s.add(Event(event_id="ev1", event_name="Demo", host_user_id="host-1",
                    teams_channel_id="chan-1"))
        s.commit()

    @contextlib.contextmanager
    def factory():
        s = Local()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    return factory, Local


class _LLM:
    """Understand step: returns whatever classification the test wants."""
    def __init__(self, doc_type):
        self._doc_type = doc_type

    def chat(self, messages, model=None):
        return '{"summary": "a file", "doc_type": "%s"}' % self._doc_type


class _Extractor:
    llm = None  # the pipeline reads extractor.llm; we inject llm explicitly instead

    def structure(self, parsed):
        return {
            "members": [{"email": "new@x.com", "display_name": "New", "role": "member"}],
            "tasks": [{"task_name": "Book room", "assignee_email": "new@x.com"}],
        }


class _Store:
    def __init__(self):
        self.payloads = []

    def put(self, payload):
        self.payloads.append(payload)
        return "pid-1"


def _pipe(doc_type, store, posted):
    return IngestionPipeline(
        graph=type("G", (), {"get_drive_item_content":
                             lambda self, d, i: (b"", "file.bin", "x")})(),
        extractor=_Extractor(), pending_store=store,
        post_card=lambda channel_id, card: posted.append((channel_id, card)),
        parse=lambda f, c: ParsedDoc(kind="docx", filename=f, text="content"),
        llm=_LLM(doc_type),
    )


def test_template_is_catalogued_without_invites(monkeypatch):
    factory, Local = _factory()
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    store, posted = _Store(), []
    res = _pipe("template", store, posted).ingest(
        drive_id="d", item_id="item-1", event_id="ev1")

    assert res.documents == 1
    assert res.doc_type == "template"
    assert res.members_added == 0 and res.tasks_added == 0 and res.invited_proposed == 0
    assert store.payloads == [] and posted == []
    # The file IS catalogued with its summary/type.
    with Local() as s:
        doc = DocumentRepository(s).get_by_drive_item("item-1")
        assert doc.doc_type == "template" and doc.summary == "a file"
        # No members were created off a non-roster file.
        assert MemberRepository(s).list("ev1") == []


def test_roster_still_proposes_invites(monkeypatch):
    factory, Local = _factory()
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    store, posted = _Store(), []
    res = _pipe("roster", store, posted).ingest(
        drive_id="d", item_id="item-2", event_id="ev1")

    assert res.members_added == 1 and res.tasks_added == 1
    assert res.invited_proposed == 1
    assert posted and posted[0][0] == "chan-1"
    assert store.payloads[0]["recipient_emails"] == ["new@x.com"]


def test_idempotent_skip(monkeypatch):
    factory, _ = _factory()
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    pipe = _pipe("roster", _Store(), [])
    first = pipe.ingest(drive_id="d", item_id="dup", event_id="ev1")
    second = pipe.ingest(drive_id="d", item_id="dup", event_id="ev1")
    assert first.documents == 1
    assert second.skipped == "already_ingested"
