"""Impl 4 — the `read_participant_file` / `send_participant_reminders` tools: registration,
identity-free schema, moderator gate, and delegation (the read tool forwards `ctx.attachments`,
which the model can't set)."""
from eventbuddy.agent.context import RequestContext
from eventbuddy.agent.tools import AgentDeps, build_tools


class _FakeSession:
    def __init__(self, current=None):
        self.current = current or {}

    def set_current_event(self, user_id, event_id):
        self.current[user_id] = event_id

    def get_current_event(self, user_id):
        return self.current.get(user_id)


def _deps(**overrides):
    calls = overrides.pop("_calls", {})

    def read_participant_file_fn(**kw):
        calls["read"] = kw
        return "summary + file_token: tok-1"

    def send_participant_reminders_fn(**kw):
        calls["send"] = kw
        return "Drafted a reminder to 2 participant(s) — choose Teams or Outlook."

    base = dict(
        session_store=_FakeSession(),
        provision_fn=lambda **kw: type("E", (), {"event_id": "ev-1"})(),
        resolve_event_fn=lambda q: "ev-7",
        remind_fn=lambda **kw: None,
        report_fn=lambda **kw: "report",
        query_tasks_fn=lambda **kw: "tasks",
        read_participant_file_fn=read_participant_file_fn,
        send_participant_reminders_fn=send_participant_reminders_fn,
    )
    base.update(overrides)
    return AgentDeps(**base), calls


def _by_name(tools):
    return {t.name: t for t in tools}


def test_tools_registered_with_identity_free_schema():
    deps, _ = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="moderator")))
    assert {"read_participant_file", "send_participant_reminders"} <= set(tools)
    assert set(tools["read_participant_file"].args) == {"link"}
    assert set(tools["send_participant_reminders"].args) == {
        "subject", "body", "file_token", "only_status"
    }
    for name in ("read_participant_file", "send_participant_reminders"):
        assert "user_id" not in tools[name].args and "attachments" not in tools[name].args


def test_read_participant_file_requires_moderator():
    deps, calls = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="m1", role="member")))
    out = tools["read_participant_file"].invoke({})
    assert "permission" in out.lower()
    assert "read" not in calls


def test_read_participant_file_forwards_context_attachments():
    deps, calls = _deps()
    atts = [{"name": "roster.csv", "download_url": "https://dl"}]
    ctx = RequestContext(user_id="h1", role="host", current_event_id="ev-3", attachments=atts)
    tools = _by_name(build_tools(deps, ctx))
    out = tools["read_participant_file"].invoke({"link": ""})
    assert "file_token" in out
    assert calls["read"] == dict(
        user_id="h1", event_id="ev-3", attachments=atts, link=""
    )


def test_send_participant_reminders_requires_moderator():
    deps, calls = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="m1", role="member")))
    out = tools["send_participant_reminders"].invoke(
        {"subject": "Reminder", "body": "Please register", "file_token": "tok-1"}
    )
    assert "permission" in out.lower()
    assert "send" not in calls


def test_send_participant_reminders_delegates_with_context_identity():
    deps, calls = _deps()
    ctx = RequestContext(user_id="h1", role="host", current_event_id="ev-3")
    tools = _by_name(build_tools(deps, ctx))
    tools["send_participant_reminders"].invoke(
        {"subject": "Register", "body": "Please", "file_token": "tok-1", "only_status": "no"}
    )
    assert calls["send"] == dict(
        user_id="h1", event_id="ev-3", subject="Register", body="Please",
        file_token="tok-1", only_status="no",
    )
