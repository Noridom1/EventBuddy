"""Impl 3, Part 0 — scope + team-id capture and the channel-scope event resolver.

Three seams: `_scope_and_team` (router derivation from the activity), `_build_channel_event_fn`
(resolve the channel's event + backfill its real team id), and `Orchestrator._build_ctx`
(channel scope → channel's event; personal scope → the caller's DM focus)."""
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from eventbuddy.agent import wiring
from eventbuddy.agent.orchestrator import Orchestrator
from eventbuddy.bot.activity_router import _scope_and_team
from eventbuddy.data.repositories.events import EventRepository
from eventbuddy.domain.models import Event

# --- router scope/team derivation ----------------------------------------------------------

def _activity(conv_type, channel_data=None):
    return SimpleNamespace(
        conversation=SimpleNamespace(id="c1", conversation_type=conv_type),
        channel_data=channel_data,
    )


def test_channel_activity_yields_channel_scope_and_team_id():
    act = _activity("channel", {"team": {"id": "team-77"}, "channel": {"id": "c1"}})
    assert _scope_and_team(act) == ("channel", "team-77")


def test_personal_activity_yields_personal_scope():
    assert _scope_and_team(_activity("personal")) == ("personal", None)


def test_group_chat_is_not_a_channel():
    assert _scope_and_team(_activity("groupChat", {"team": {"id": "x"}})) == ("personal", None)


def test_channel_without_team_data_degrades_to_none_team():
    assert _scope_and_team(_activity("channel", {})) == ("channel", None)


# --- channel-scope event resolver + backfill ----------------------------------------------

def _factory_with(events):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Event.__table__.create(engine)
    Local = sessionmaker(bind=engine, expire_on_commit=False)
    with Local() as s:
        for e in events:
            s.add(Event(**e))
        s.commit()
    import contextlib

    @contextlib.contextmanager
    def factory():
        s = Local()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    return factory


def test_channel_event_fn_resolves_and_backfills_team_id(monkeypatch):
    factory = _factory_with([{"event_id": "ev1", "event_name": "Launch",
                              "teams_channel_id": "ch-1", "teams_team_id": None}])
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    fn = wiring._build_channel_event_fn()

    assert fn(channel_id="ch-1", team_id="team-9") == "ev1"
    # backfilled
    with factory() as s:
        assert EventRepository(s).get("ev1").teams_team_id == "team-9"


def test_channel_event_fn_does_not_overwrite_existing_team_id(monkeypatch):
    factory = _factory_with([{"event_id": "ev1", "event_name": "Launch",
                              "teams_channel_id": "ch-1", "teams_team_id": "original"}])
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    fn = wiring._build_channel_event_fn()
    fn(channel_id="ch-1", team_id="new-id")
    with factory() as s:
        assert EventRepository(s).get("ev1").teams_team_id == "original"


def test_channel_event_fn_unbound_channel_returns_none(monkeypatch):
    factory = _factory_with([])
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    fn = wiring._build_channel_event_fn()
    assert fn(channel_id="nope", team_id="t") is None


# --- orchestrator context building ---------------------------------------------------------

class _FakeSession:
    def __init__(self, current=None):
        self._current = current or {}

    def get_current_event(self, user_id):
        return self._current.get(user_id)


def _orch(channel_event_fn=None, session=None):
    return Orchestrator(
        session_store=session or _FakeSession(),
        provision_fn=lambda **kw: None, resolve_event_fn=lambda q: None,
        remind_fn=lambda **kw: None, report_fn=lambda **kw: "", query_tasks_fn=lambda **kw: "",
        channel_event_fn=channel_event_fn,
    )


def test_build_ctx_channel_scope_uses_channel_event():
    calls = {}

    def channel_event_fn(*, channel_id, team_id=None):
        calls.update(channel_id=channel_id, team_id=team_id)
        return "ev-bound"

    ctx = _orch(channel_event_fn)._build_ctx("u1", "ch-1", "channel", None, "team-3")
    assert ctx.current_event_id == "ev-bound" and ctx.scope == "channel"
    assert calls == {"channel_id": "ch-1", "team_id": "team-3"}


def test_build_ctx_personal_scope_uses_session_focus():
    orch = _orch(session=_FakeSession({"u1": "ev-dm"}))
    ctx = orch._build_ctx("u1", None, "personal", None)
    assert ctx.current_event_id == "ev-dm" and ctx.scope == "personal"
