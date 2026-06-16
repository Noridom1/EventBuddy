"""Impl 18 — domain-identity member enrollment & sync.

Covers the identity-set matching (email + AAD id + Bot Framework id), the identity-aware
repositories, the roster-sync closure (enroll all group members, idempotent, host-merge,
skip non-AAD), `setup_event` enroll-all, and the auto-enroll upsert backfill. Repositories
are exercised on sqlite; the wiring closures sqlite-redirect `session_scope` (same pattern as
test_setup_event.py / test_cross_context.py)."""
import contextlib

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from eventbuddy.agent import wiring
from eventbuddy.data.repositories.events import EventRepository
from eventbuddy.data.repositories.members import MemberRepository
from eventbuddy.data.repositories.tasks import TaskRepository
from eventbuddy.domain.identity import CallerIdentity
from eventbuddy.domain.models import Event, EventMember, Task


def _factory(seed=()):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Event.__table__.create(engine)
    EventMember.__table__.create(engine)
    Task.__table__.create(engine)
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


class _FakeGraph:
    """A stand-in Graph client returning a fixed chat/channel roster."""

    def __init__(self, members):
        self._members = members
        self.chat_calls, self.channel_calls = [], []

    def list_chat_members(self, chat_id):
        self.chat_calls.append(chat_id)
        return self._members

    def list_channel_members(self, team_id, channel_id):
        self.channel_calls.append((team_id, channel_id))
        return self._members


# --- repositories: identity matching --------------------------------------------------------

def test_get_by_identity_matches_any_field():
    _, Local = _factory([
        Event(event_id="ev1", event_name="Launch"),
        EventMember(event_id="ev1", aad_object_id="AAD-1", email="alice@corp",
                    display_name="Alice", role="member"),
    ])
    with Local() as s:
        repo = MemberRepository(s)
        # Found by AAD id alone (the DM bridge), and by email alone — neither is the BF id.
        assert repo.get_by_identity("ev1", CallerIdentity.of(aad_object_id="AAD-1")) is not None
        assert repo.get_by_identity("ev1", CallerIdentity.of(email="ALICE@corp")) is not None
        assert repo.get_by_identity("ev1", CallerIdentity.of(teams_user_id="29:x")) is None


def test_upsert_member_backfills_bf_id_onto_existing_row():
    factory, Local = _factory([
        Event(event_id="ev1", event_name="Launch"),
        EventMember(event_id="ev1", aad_object_id="AAD-1", email="alice@corp",
                    display_name="Alice", role="member"),
    ])
    with Local() as s:
        repo = MemberRepository(s)
        # Same human, now seen by their Bot Framework id + AAD id — must merge, not duplicate.
        row = repo.upsert_member("ev1", {
            "teams_user_id": "29:alice", "aad_object_id": "AAD-1", "role": "member",
        })
        s.commit()
        assert row.teams_user_id == "29:alice"  # backfilled
    rows = _members(Local, "ev1")
    assert len(rows) == 1 and rows[0].teams_user_id == "29:alice"


def test_upsert_member_does_not_downgrade_role():
    _, Local = _factory([
        Event(event_id="ev1", event_name="Launch"),
        EventMember(event_id="ev1", aad_object_id="AAD-1", role="host"),
    ])
    with Local() as s:
        repo = MemberRepository(s)
        repo.upsert_member("ev1", {"aad_object_id": "AAD-1", "role": "member"})
        s.commit()
    assert _members(Local, "ev1")[0].role == "host"  # host preserved


def test_list_for_identity_finds_group_event_from_dm_identity():
    # Enrolled from a group roster by AAD id + email (no BF id yet); the DM context supplies the
    # BF id + the same AAD id → the event must surface.
    _, Local = _factory([
        Event(event_id="ev1", event_name="Launch", status="ideation", host_user_id="host"),
        EventMember(event_id="ev1", aad_object_id="AAD-1", email="a@corp", role="member"),
    ])
    with Local() as s:
        rows = EventRepository(s).list_for_identity(
            CallerIdentity.of(teams_user_id="29:a", aad_object_id="AAD-1"))
    assert [ev.event_id for ev, _ in rows] == ["ev1"]


def test_by_assignee_identity_matches_email():
    _, Local = _factory([
        Event(event_id="ev1", event_name="Launch"),
        Task(task_id="t1", event_id="ev1", task_name="Slides", assignee_email="a@corp"),
    ])
    with Local() as s:
        tasks = TaskRepository(s).by_assignee_identity(
            CallerIdentity.of(teams_user_id="29:a", email="A@corp"), "ev1")
    assert [t.task_id for t in tasks] == ["t1"]


# --- sync closure ---------------------------------------------------------------------------

def test_sync_enrolls_all_group_members(monkeypatch):
    factory, Local = _factory([Event(event_id="ev1", event_name="Launch",
                                      teams_channel_id="conv-1")])
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    graph = _FakeGraph([
        {"id": "AAD-1", "display_name": "Alice", "email": "alice@corp"},
        {"id": "AAD-2", "display_name": "Bob", "email": "bob@corp"},
        {"id": "", "display_name": "Guest", "email": ""},  # non-AAD → skipped
    ])
    fn = wiring._build_sync_members_fn(graph_factory=lambda: graph)
    result = fn(event_id="ev1", channel_id="conv-1", scope="group")
    assert result["ok"] and len(result["added"]) == 2 and result["skipped"] == 1
    assert graph.chat_calls == ["conv-1"]
    rows = _members(Local, "ev1")
    assert {r.email for r in rows} == {"alice@corp", "bob@corp"}


def test_sync_is_idempotent_and_merges_actor_host(monkeypatch):
    # Alice is already enrolled as host by her BF id (setup_event), with no AAD/email yet.
    factory, Local = _factory([
        Event(event_id="ev1", event_name="Launch", teams_channel_id="conv-1"),
        EventMember(event_id="ev1", teams_user_id="29:alice", role="host"),
    ])
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    graph = _FakeGraph([
        {"id": "AAD-1", "display_name": "Alice", "email": "alice@corp"},
        {"id": "AAD-2", "display_name": "Bob", "email": "bob@corp"},
    ])
    fn = wiring._build_sync_members_fn(graph_factory=lambda: graph)
    actor = CallerIdentity.of(teams_user_id="29:alice", aad_object_id="AAD-1",
                              email="alice@corp")
    result = fn(event_id="ev1", channel_id="conv-1", scope="group", actor_identity=actor)
    rows = _members(Local, "ev1")
    assert len(rows) == 2  # Alice merged onto her host row (not duplicated), Bob added
    alice = next(r for r in rows if r.teams_user_id == "29:alice")
    assert alice.role == "host" and alice.aad_object_id == "AAD-1" and alice.email == "alice@corp"
    assert result["added"] == ["Bob"] and result["already"] == 1

    # Re-running adds nothing.
    again = fn(event_id="ev1", channel_id="conv-1", scope="group", actor_identity=actor)
    assert again["added"] == [] and len(_members(Local, "ev1")) == 2


def test_sync_degrades_without_graph(monkeypatch):
    monkeypatch.setattr(wiring, "_graph_creds", lambda: True)
    fn = wiring._build_sync_members_fn(graph_factory=lambda: None)  # not signed in
    result = fn(event_id="ev1", channel_id="conv-1", scope="group")
    assert result["ok"] is False and "sign in" in result["message"].lower()


def test_sync_channel_scope_uses_channel_endpoint(monkeypatch):
    factory, _ = _factory([Event(event_id="ev1", event_name="Launch",
                                 teams_channel_id="ch-1", teams_team_id="team-9")])
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    graph = _FakeGraph([{"id": "AAD-1", "display_name": "Alice", "email": "a@corp"}])
    fn = wiring._build_sync_members_fn(graph_factory=lambda: graph)
    result = fn(event_id="ev1", channel_id="ch-1", team_id="team-9", scope="channel")
    assert result["ok"] and graph.channel_calls == [("team-9", "ch-1")]


# --- setup_event enroll-all + autoenroll backfill -------------------------------------------

def test_setup_event_enrolls_whole_group(monkeypatch):
    factory, Local = _factory()
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    graph = _FakeGraph([
        {"id": "AAD-1", "display_name": "Alice", "email": "alice@corp"},
        {"id": "AAD-2", "display_name": "Bob", "email": "bob@corp"},
    ])
    sync_fn = wiring._build_sync_members_fn(graph_factory=lambda: graph)
    fn = wiring._build_setup_event_fn(sync_members_fn=sync_fn)

    out = fn(name="Launch", user_id="29:alice", channel_id="conv-1", team_id="team-9",
             scope="group", display_name="Alice", aad_object_id="AAD-1", email="alice@corp")
    assert "Enrolled" in out
    with Local() as s:
        ev = s.scalar(select(Event).where(Event.event_name == "Launch"))
    rows = _members(Local, ev.event_id)
    # Alice (host, merged) + Bob — never a duplicate Alice row.
    assert len(rows) == 2
    alice = next(r for r in rows if r.aad_object_id == "AAD-1")
    assert alice.role == "host" and alice.teams_user_id == "29:alice"


def test_autoenroll_backfills_aad_enrolled_member(monkeypatch):
    # Bob was enrolled by the group sync (AAD id + email, no BF id). When he later posts, his BF
    # id must backfill onto that SAME row.
    factory, Local = _factory([
        Event(event_id="ev1", event_name="Launch", teams_channel_id="conv-1"),
        EventMember(event_id="ev1", aad_object_id="AAD-2", email="bob@corp",
                    display_name="Bob", role="member"),
    ])
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    fn = wiring._build_member_autoenroll_fn()
    fn(event_id="ev1", user_id="29:bob", display_name="Bob", aad_object_id="AAD-2",
       email="bob@corp")
    rows = _members(Local, "ev1")
    assert len(rows) == 1 and rows[0].teams_user_id == "29:bob"  # backfilled, not duplicated
