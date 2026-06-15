"""Impl 3, Part 3 — the brainstorm channel read (`wiring._build_read_channel_fn`).

Exercises the read-only guard chain: needs a focused event, Graph creds, a bound channel, a
known team id, and membership; only then does it call Graph and wrap the result as untrusted
external content. Graph is injected; `session_scope` is sqlite-redirected (same pattern as
test_cross_context.py)."""
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


class _FakeGraph:
    def __init__(self, msgs):
        self.msgs = msgs
        self.calls = []

    def list_channel_messages(self, team_id, channel_id, limit):
        self.calls.append((team_id, channel_id, limit))
        return self.msgs


def _enable_graph(monkeypatch):
    # _graph_creds() reads settings; make it truthy so the read path runs.
    for k in ("graph_tenant_id", "graph_client_id", "graph_client_secret"):
        monkeypatch.setattr(wiring.settings, k, "set")


def _build(monkeypatch, factory, graph):
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    return wiring._build_read_channel_fn(graph_factory=lambda: graph)


def test_member_gets_wrapped_discussion(monkeypatch):
    _enable_graph(monkeypatch)
    factory = _factory_with(
        {"event_id": "ev1", "event_name": "Launch", "teams_channel_id": "ch-1",
         "teams_team_id": "team-9", "host_user_id": "host"},
        [{"teams_user_id": "u1", "email": "u1@x.com"}],
    )
    graph = _FakeGraph([
        {"author": "Bob", "text": "second idea"},   # Graph returns newest-first
        {"author": "Alice", "text": "first idea"},
    ])
    fn = _build(monkeypatch, factory, graph)
    out = fn(user_id="u1", event_id="ev1", limit=30)
    assert graph.calls == [("team-9", "ch-1", 30)]
    assert "external_untrusted_content" in out
    # rendered oldest-first
    assert out.index("Alice: first idea") < out.index("Bob: second idea")


def test_non_member_is_refused_without_reading(monkeypatch):
    _enable_graph(monkeypatch)
    factory = _factory_with(
        {"event_id": "ev1", "event_name": "Launch", "teams_channel_id": "ch-1",
         "teams_team_id": "team-9", "host_user_id": "host"},
        [{"teams_user_id": "someone", "email": "s@x.com"}],
    )
    graph = _FakeGraph([{"author": "A", "text": "secret"}])
    fn = _build(monkeypatch, factory, graph)
    out = fn(user_id="intruder", event_id="ev1")
    assert "not a member" in out.lower()
    assert graph.calls == []  # guard short-circuits before the Graph call


def test_host_can_read_even_without_membership_row(monkeypatch):
    _enable_graph(monkeypatch)
    factory = _factory_with(
        {"event_id": "ev1", "event_name": "Launch", "teams_channel_id": "ch-1",
         "teams_team_id": "team-9", "host_user_id": "h1"},
        [],
    )
    graph = _FakeGraph([{"author": "A", "text": "idea"}])
    fn = _build(monkeypatch, factory, graph)
    out = fn(user_id="h1", event_id="ev1")
    assert "external_untrusted_content" in out


def test_missing_team_id_degrades_cleanly(monkeypatch):
    _enable_graph(monkeypatch)
    factory = _factory_with(
        {"event_id": "ev1", "event_name": "Launch", "teams_channel_id": "ch-1",
         "teams_team_id": None, "host_user_id": "h1"},
        [{"teams_user_id": "u1", "email": "u1@x.com"}],
    )
    graph = _FakeGraph([{"author": "A", "text": "idea"}])
    fn = _build(monkeypatch, factory, graph)
    out = fn(user_id="u1", event_id="ev1")
    assert "team id" in out.lower()
    assert graph.calls == []


def test_no_focused_event_guides(monkeypatch):
    fn = wiring._build_read_channel_fn(graph_factory=lambda: _FakeGraph([]))
    assert "focus" in fn(user_id="u1", event_id=None).lower()


def test_no_graph_creds_degrades(monkeypatch):
    # No Graph auth at all: neither delegated (OAuth connection) nor app-only creds (Plan 13).
    monkeypatch.setattr(wiring.settings, "graph_oauth_connection_name", "")
    monkeypatch.setattr(wiring.settings, "graph_tenant_id", "")
    monkeypatch.setattr(wiring.settings, "graph_client_id", "")
    monkeypatch.setattr(wiring.settings, "graph_client_secret", "")
    fn = wiring._build_read_channel_fn(graph_factory=lambda: _FakeGraph([]))
    assert "graph" in fn(user_id="u1", event_id="ev1").lower()
