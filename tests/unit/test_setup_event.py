"""Group/channel onboarding — `setup_event_fn` (bind this conversation to an event,
resolve-or-create, enroll caller as host) and `member_autoenroll_fn` (enroll a posting user
into the bound event). Both reuse the repositories directly and resolve `session_scope` lazily,
so we sqlite-redirect that module attribute (same pattern as test_cross_context.py)."""
import contextlib

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from eventbuddy.agent import wiring
from eventbuddy.domain.models import Event, EventMember


def _factory(seed=()):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Event.__table__.create(engine)
    EventMember.__table__.create(engine)
    Local = sessionmaker(bind=engine, expire_on_commit=False)
    with Local() as s:
        for row in seed:
            s.add(row)
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


def _members(Local, event_id):
    with Local() as s:
        return list(s.scalars(select(EventMember).where(EventMember.event_id == event_id)))


# --- setup_event_fn --------------------------------------------------------------------------

def test_setup_creates_event_binds_and_enrolls_host(monkeypatch):
    factory, Local = _factory()
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    fn = wiring._build_setup_event_fn()

    out = fn(name="Spring Hackathon", user_id="u1", channel_id="conv-1", team_id="team-9",
             scope="group", display_name="Alice")
    assert "Created and set up" in out and "Spring Hackathon" in out

    with Local() as s:
        ev = s.scalar(select(Event).where(Event.event_name == "Spring Hackathon"))
        assert ev is not None
        assert ev.teams_channel_id == "conv-1"  # bound to THIS conversation
        assert ev.teams_team_id == "team-9"
        assert ev.host_user_id == "u1"
    rows = _members(Local, ev.event_id)
    assert len(rows) == 1
    assert rows[0].teams_user_id == "u1" and rows[0].role == "host" and rows[0].email is None


def test_setup_resolves_existing_event_by_name(monkeypatch):
    factory, Local = _factory([
        Event(event_id="ev1", event_name="AI Workshop", status="ideation", host_user_id="host"),
    ])
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    fn = wiring._build_setup_event_fn()

    out = fn(name="AI Workshop", user_id="u2", channel_id="conv-2", scope="channel")
    assert "Set up" in out and "AI Workshop" in out

    with Local() as s:
        ev = s.get(Event, "ev1")
        assert ev.teams_channel_id == "conv-2"  # existing event, now bound — no duplicate created
        assert s.scalar(select(Event).where(Event.event_name == "AI Workshop")) is ev
        assert len(list(s.scalars(select(Event)))) == 1


def test_setup_idempotent_when_already_bound_to_same_event(monkeypatch):
    factory, Local = _factory([
        Event(event_id="ev1", event_name="Launch", teams_channel_id="conv-1", host_user_id="h"),
    ])
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    fn = wiring._build_setup_event_fn()

    out = fn(name="Launch", user_id="u1", channel_id="conv-1", scope="group", role="member")
    assert "already set up" in out.lower()
    assert _members(Local, "ev1") == []  # no enrollment on the idempotent path


def test_rebind_to_other_event_requires_moderator(monkeypatch):
    factory, Local = _factory([
        Event(event_id="ev1", event_name="Old", teams_channel_id="conv-1", host_user_id="h"),
        Event(event_id="ev2", event_name="New", host_user_id="h"),
    ])
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    fn = wiring._build_setup_event_fn()

    # A plain member can't repoint a bound conversation.
    denied = fn(name="New", user_id="u1", channel_id="conv-1", scope="group", role="member")
    assert "host or moderator" in denied.lower()
    with Local() as s:
        assert s.get(Event, "ev1").teams_channel_id == "conv-1"  # unchanged
        assert s.get(Event, "ev2").teams_channel_id is None

    # A host can — the old binding is freed and re-pointed.
    ok = fn(name="New", user_id="u1", channel_id="conv-1", scope="group", role="host")
    assert "New" in ok
    with Local() as s:
        assert s.get(Event, "ev1").teams_channel_id is None
        assert s.get(Event, "ev2").teams_channel_id == "conv-1"


def test_setup_rejected_in_dm():
    fn = wiring._build_setup_event_fn()
    out = fn(name="X", user_id="u1", channel_id=None, scope="personal")
    assert "create_event" in out


# --- member_autoenroll_fn --------------------------------------------------------------------

def test_autoenroll_adds_member_by_teams_id(monkeypatch):
    factory, Local = _factory([
        Event(event_id="ev1", event_name="Launch", teams_channel_id="conv-1", host_user_id="h"),
    ])
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    fn = wiring._build_member_autoenroll_fn()

    fn(event_id="ev1", user_id="u2", display_name="Bob")
    rows = _members(Local, "ev1")
    assert len(rows) == 1
    assert rows[0].teams_user_id == "u2" and rows[0].role == "member" and rows[0].email is None


def test_autoenroll_idempotent(monkeypatch):
    factory, Local = _factory([
        Event(event_id="ev1", event_name="Launch", teams_channel_id="conv-1", host_user_id="h"),
        EventMember(event_id="ev1", teams_user_id="u2", display_name="Bob", role="member"),
    ])
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    fn = wiring._build_member_autoenroll_fn()

    fn(event_id="ev1", user_id="u2", display_name="Bob")
    assert len(_members(Local, "ev1")) == 1  # no duplicate


def test_autoenroll_noop_without_event():
    fn = wiring._build_member_autoenroll_fn()
    # No event_id → returns without touching the DB (no session_scope patched, so a DB hit
    # would error — this asserts the early return).
    assert fn(event_id=None, user_id="u2") is None
