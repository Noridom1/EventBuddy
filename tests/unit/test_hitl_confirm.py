"""Authorization + dispatch logic of the HITL confirm handler (Implementation 1).

`ConfirmHandler.resolve` is the pure decision: pop the one-shot pending action, re-authorize
the clicker (cross-cutting rule 2 — never trust the card), and hand off to an injected
`execute_fn` for the side effects. Tested here with fakes — no Bot Framework, no Graph, no DB."""
from eventbuddy.bot.confirm import ConfirmHandler


class _Pending:
    """One-shot pending store: `pop` returns the payload once, then None (replay)."""

    def __init__(self, payload):
        self._payload = payload
        self.pops = 0

    def pop(self, pending_id):
        self.pops += 1
        p, self._payload = self._payload, None
        return p


def _handler(payload, *, role="host", execute=None):
    calls = {}

    def execute_fn(*, payload, channel, actor, authorized):
        calls["execute"] = dict(payload=payload, channel=channel, actor=actor,
                                authorized=authorized)
        return (execute if execute is not None else (True, "✅ done"))

    h = ConfirmHandler(
        pending_store=_Pending(payload),
        role_resolver=lambda **kw: role,
        execute_fn=execute_fn,
    )
    return h, calls


_PAYLOAD = {"type": "remind", "event_id": "ev1", "requested_by": "u1",
            "recipient_emails": ["a@x.com"]}


def test_valid_confirm_executes_authorized_and_returns_summary():
    h, calls = _handler(_PAYLOAD, role="moderator")
    out = h.resolve(action="remind", pending_id="p1", channel="outlook", clicker="u1")
    assert out == "✅ done"
    assert calls["execute"]["authorized"] is True
    assert calls["execute"]["actor"] == "u1"
    assert calls["execute"]["channel"] == "outlook"
    assert calls["execute"]["payload"]["event_id"] == "ev1"


def test_missing_pending_id_is_expired():
    h, calls = _handler(_PAYLOAD)
    out = h.resolve(action="remind", pending_id=None, channel="outlook", clicker="u1")
    assert "expired" in out.lower()
    assert "execute" not in calls  # nothing ran


def test_replayed_token_is_expired_and_does_not_execute():
    h, calls = _handler(_PAYLOAD, role="moderator")
    first = h.resolve(action="remind", pending_id="p1", channel="outlook", clicker="u1")
    second = h.resolve(action="remind", pending_id="p1", channel="outlook", clicker="u1")
    assert first == "✅ done"
    assert "expired" in second.lower()


def test_other_user_is_denied():
    # Clicker is not the user who prepared the action → denied (still calls execute so it can
    # audit the denial, but the reply is the refusal).
    h, calls = _handler(_PAYLOAD, role="host")
    out = h.resolve(action="remind", pending_id="p1", channel="outlook", clicker="intruder")
    assert "not allowed" in out.lower()
    assert calls["execute"]["authorized"] is False


def test_role_below_moderator_is_denied():
    h, calls = _handler(_PAYLOAD, role="member")  # right user, insufficient role
    out = h.resolve(action="remind", pending_id="p1", channel="outlook", clicker="u1")
    assert "not allowed" in out.lower()
    assert calls["execute"]["authorized"] is False


def test_member_floor_payload_confirmable_by_member_drafter():
    # Generic send (send_email/send_teams_message) carries min_role=member → the drafting member
    # can confirm their own send even though the handler defaults to a moderator gate.
    payload = {"type": "teams_dm", "event_id": None, "requested_by": "u1",
               "target_user_id": "u-9", "min_role": "member"}
    h, calls = _handler(payload, role="member")
    out = h.resolve(action="teams_dm", pending_id="p1", channel=None, clicker="u1")
    assert out == "✅ done"
    assert calls["execute"]["authorized"] is True


def test_member_floor_still_requires_drafter():
    # The drafter==clicker check always applies, even with a member floor.
    payload = {"type": "teams_dm", "event_id": None, "requested_by": "u1",
               "target_user_id": "u-9", "min_role": "member"}
    h, calls = _handler(payload, role="member")
    out = h.resolve(action="teams_dm", pending_id="p1", channel=None, clicker="intruder")
    assert "not allowed" in out.lower()
    assert calls["execute"]["authorized"] is False


def test_event_payload_without_floor_keeps_moderator_gate():
    # No min_role key → unchanged: a member is denied on an event action.
    h, calls = _handler(_PAYLOAD, role="member")
    out = h.resolve(action="remind", pending_id="p1", channel="outlook", clicker="u1")
    assert "not allowed" in out.lower()
    assert calls["execute"]["authorized"] is False


def test_redis_failure_degrades_to_expired():
    class _Boom:
        def pop(self, pending_id):
            raise RuntimeError("redis down")

    h = ConfirmHandler(pending_store=_Boom(), role_resolver=lambda **kw: "host",
                       execute_fn=lambda **kw: (True, "x"))
    out = h.resolve(action="remind", pending_id="p1", channel="outlook", clicker="u1")
    assert "expired" in out.lower()  # never a 500
