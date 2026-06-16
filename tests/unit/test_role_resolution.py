"""Server-resolved caller role policy (`_default_role`) + the orchestrator seam that stamps it
onto `RequestContext`. A group chat is a flat peer space: every participant resolves to
`moderator` regardless of any focused event / `EventMember` row, so anyone can run the
privileged actions. A 1-1 DM resolves to `host`; a channel falls back to `member` (overridden by
the membership-backed resolver wired in `build_orchestrator`)."""
from eventbuddy.agent.orchestrator import Orchestrator, _default_role


def test_default_role_personal_is_host():
    assert _default_role(user_id="u1", scope="personal", channel_id=None) == "host"


def test_default_role_group_is_moderator():
    assert _default_role(user_id="u1", scope="group", channel_id="19:c@thread.v2") == "moderator"


def test_default_role_group_ignores_focused_event():
    # A flat peer space: a focused event must never downgrade a group participant.
    assert _default_role(
        user_id="u1", scope="group", channel_id="19:c@thread.v2", event_id="ev-bound"
    ) == "moderator"


def test_default_role_channel_is_member():
    assert _default_role(user_id="u1", scope="channel", channel_id="c1") == "member"


# --- the orchestrator stamps the resolved role onto ctx --------------------------------------

class _FakeSession:
    def __init__(self):
        self.current = {}

    def get_current_event(self, user_id):
        return self.current.get(user_id)

    def set_current_event(self, user_id, event_id):
        self.current[user_id] = event_id


class _FakeRunner:
    def __init__(self):
        self.seen = []

    def run(self, text, ctx):
        self.seen.append((text, ctx))
        return "ok"


def _deps():
    return dict(
        session_store=_FakeSession(),
        provision_fn=lambda **kw: type("E", (), {"event_id": "ev-1"})(),
        resolve_event_fn=lambda q, **kw: "ev-7",
        remind_fn=lambda **kw: None,
        report_fn=lambda **kw: "report",
        query_tasks_fn=lambda **kw: "tasks",
    )


def test_group_participant_resolves_to_moderator_even_when_event_bound():
    runner = _FakeRunner()
    orch = Orchestrator(
        **_deps(), runner=runner,
        channel_event_fn=lambda *, channel_id, team_id=None: "ev-bound",
    )
    orch.handle(user_id="u1", channel_id="conv-1", text="hi", scope="group", team_id="team-9")
    _, ctx = runner.seen[0]
    assert ctx.current_event_id == "ev-bound"
    assert ctx.role == "moderator"  # peer, not downgraded by the binding


def test_dm_participant_resolves_to_host():
    runner = _FakeRunner()
    orch = Orchestrator(**_deps(), runner=runner)
    orch.handle(user_id="u1", channel_id=None, text="hi")  # personal scope
    _, ctx = runner.seen[0]
    assert ctx.role == "host"
