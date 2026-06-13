"""Phase 1.9, Part B — the guarded DM→event cross-context read (`event_context_fn`).

Exercises the security model in `wiring._build_event_context_fn`: event id is server-
resolved (the closure takes it as an arg from the tool, but the tool never exposes it to
the model — see test_tools.py), membership is enforced, a missing channel degrades to empty,
and only L2 (transcript) + L3 (summary) are read — never L1."""
import contextlib

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from eventbuddy.agent import wiring
from eventbuddy.domain.models import Event, EventMember


def _factory_with(event_kwargs, members):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Event.__table__.create(engine)
    EventMember.__table__.create(engine)
    Local = sessionmaker(bind=engine, expire_on_commit=False)
    with Local() as s:
        s.add(Event(**event_kwargs))
        for m in members:
            s.add(EventMember(event_id=event_kwargs["event_id"], **m))
        s.commit()

    @contextlib.contextmanager
    def factory():
        s = Local()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    return factory


class _FakeTranscript:
    def __init__(self):
        self.rehydrated = []

    def rehydrate(self, thread_id, budget=4096):
        self.rehydrated.append((thread_id, budget))
        return []


class _FakeSummarizer:
    def __init__(self, summary):
        self._summary = summary
        self.read = []

    def get_summary(self, thread_id):
        self.read.append(thread_id)
        return self._summary


def _build(monkeypatch, factory, transcript, summarizer):
    # The closure imports session_scope at call-time, so patching the module attribute
    # redirects its repo reads to our sqlite-backed factory.
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    return wiring._build_event_context_fn(transcript, summarizer)


def test_member_gets_event_summary(monkeypatch):
    factory = _factory_with(
        {"event_id": "ev-1", "event_name": "Launch", "teams_channel_id": "ch-1"},
        [{"teams_user_id": "u1", "email": "u1@x.com"}],
    )
    tr, sm = _FakeTranscript(), _FakeSummarizer("We agreed on Friday.")
    fn = _build(monkeypatch, factory, tr, sm)
    out = fn(user_id="u1", event_id="ev-1")
    assert "Context from event 'Launch'" in out
    assert "We agreed on Friday." in out
    # read L3 + L2 of the EVENT thread (keyed on the bound channel), never L1
    assert sm.read == ["event:ch-1"]
    assert tr.rehydrated and tr.rehydrated[0][0] == "event:ch-1"


def test_non_member_gets_empty(monkeypatch):
    factory = _factory_with(
        {"event_id": "ev-1", "event_name": "Launch", "teams_channel_id": "ch-1"},
        [{"teams_user_id": "someone-else", "email": "other@x.com"}],
    )
    tr, sm = _FakeTranscript(), _FakeSummarizer("secret")
    fn = _build(monkeypatch, factory, tr, sm)
    assert fn(user_id="intruder", event_id="ev-1") == ""
    assert sm.read == []  # guard short-circuits before any memory read


def test_no_channel_bound_gets_empty(monkeypatch):
    factory = _factory_with(
        {"event_id": "ev-1", "event_name": "Launch", "teams_channel_id": None},
        [{"teams_user_id": "u1", "email": "u1@x.com"}],
    )
    tr, sm = _FakeTranscript(), _FakeSummarizer("summary")
    fn = _build(monkeypatch, factory, tr, sm)
    assert fn(user_id="u1", event_id="ev-1") == ""


def test_no_focused_event_gets_empty(monkeypatch):
    factory = _factory_with(
        {"event_id": "ev-1", "event_name": "Launch", "teams_channel_id": "ch-1"}, []
    )
    tr, sm = _FakeTranscript(), _FakeSummarizer("summary")
    fn = _build(monkeypatch, factory, tr, sm)
    assert fn(user_id="u1", event_id=None) == ""
