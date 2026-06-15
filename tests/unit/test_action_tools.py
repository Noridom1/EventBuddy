"""Impl 1 tool wiring: `update_task` (direct), `send_outlook_mail` (HITL), and the
`prepare_reminders` return passthrough. Tested via `build_tools` with fake capability
closures — no DB/Redis/Graph (same pattern as test_tools.py)."""
from eventbuddy.agent.context import RequestContext
from eventbuddy.agent.tools import AgentDeps, build_tools


class _FakeSession:
    def __init__(self):
        self.current = {}

    def set_current_event(self, user_id, event_id):
        self.current[user_id] = event_id

    def get_current_event(self, user_id):
        return self.current.get(user_id)


def _deps(**overrides):
    calls = overrides.pop("_calls", {})

    def update_task_fn(**kw):
        calls["update"] = kw
        return f"updated:{kw['status']}"

    def send_mail_fn(**kw):
        calls["mail"] = kw
        return "Drafted the email — confirm on the card to send."

    base = dict(
        session_store=_FakeSession(),
        provision_fn=lambda **kw: type("E", (), {"event_id": "ev-1"})(),
        resolve_event_fn=lambda q: "ev-7",
        remind_fn=lambda **kw: None,
        report_fn=lambda **kw: "report",
        query_tasks_fn=lambda **kw: "tasks",
        update_task_fn=update_task_fn,
        send_mail_fn=send_mail_fn,
    )
    base.update(overrides)
    return AgentDeps(**base), calls


def _by_name(tools):
    return {t.name: t for t in tools}


def test_new_tools_registered_and_identity_absent():
    deps, _ = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="moderator")))
    assert {"update_task", "send_outlook_mail"} <= set(tools)
    for name in ("update_task", "send_outlook_mail"):
        assert "user_id" not in tools[name].args and "role" not in tools[name].args


def test_update_task_schema_is_query_and_status_only():
    deps, _ = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="member")))
    assert set(tools["update_task"].args) == {"task_query", "status"}


def test_setup_event_tool_passes_ctx_and_hides_identity():
    calls = {}
    deps, _ = _deps(setup_event_fn=lambda **kw: calls.update(kw) or "ok")
    ctx = RequestContext(user_id="u1", channel_id="conv-1", team_id="team-9", scope="group",
                         role="member", display_name="Alice")
    tools = _by_name(build_tools(deps, ctx))
    # The model only chooses name + objective; identity/conversation/scope come from ctx.
    assert set(tools["setup_event"].args) == {"name", "objective"}
    tools["setup_event"].invoke({"name": "Spring Hackathon", "objective": "a hackathon"})
    assert calls == {
        "name": "Spring Hackathon", "user_id": "u1", "channel_id": "conv-1",
        "team_id": "team-9", "scope": "group", "role": "member",
        "display_name": "Alice", "objective": "a hackathon",
    }


def test_update_task_needs_focused_event():
    deps, calls = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="member")))
    out = tools["update_task"].invoke({"task_query": "slides", "status": "done"})
    assert "focus" in out.lower()
    assert "update" not in calls  # closure not called without an event


def test_update_task_delegates_with_context_identity_and_role():
    deps, calls = _deps()
    deps.session_store.set_current_event("u1", "ev-3")
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="moderator")))
    out = tools["update_task"].invoke({"task_query": "slides", "status": "done"})
    assert out == "updated:done"
    assert calls["update"] == dict(
        user_id="u1", role="moderator", event_id="ev-3", task_query="slides", status="done"
    )


def test_send_outlook_mail_requires_moderator():
    deps, calls = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="m1", role="member")))
    out = tools["send_outlook_mail"].invoke({"subject": "Hi", "body": "x"})
    assert "permission" in out.lower()
    assert "mail" not in calls  # body never called for a non-moderator


def test_send_outlook_mail_delegates_for_moderator():
    deps, calls = _deps()
    deps.session_store.set_current_event("h1", "ev-3")
    tools = _by_name(build_tools(deps, RequestContext(user_id="h1", role="host")))
    out = tools["send_outlook_mail"].invoke({"subject": "Hi", "body": "x"})
    assert "confirm" in out.lower()
    assert calls["mail"]["subject"] == "Hi" and calls["mail"]["event_id"] == "ev-3"


def test_send_outlook_mail_coerces_string_recipient_to_list():
    # Models routinely emit a bare string for a single address — the tool must coerce it so
    # `send_mail_fn` always receives a list (the Pydantic schema would otherwise reject it).
    deps, calls = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="h1", role="host")))
    tools["send_outlook_mail"].invoke(
        {"subject": "Hi", "body": "x", "recipients": "a@x.com"}
    )
    assert calls["mail"]["recipients"] == ["a@x.com"]


def test_send_outlook_mail_splits_delimited_recipient_string():
    deps, calls = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="h1", role="host")))
    tools["send_outlook_mail"].invoke(
        {"subject": "Hi", "body": "x", "recipients": "a@x.com, b@y.com; c@z.com"}
    )
    assert calls["mail"]["recipients"] == ["a@x.com", "b@y.com", "c@z.com"]


def test_send_outlook_mail_passes_list_recipient_unchanged():
    deps, calls = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="h1", role="host")))
    tools["send_outlook_mail"].invoke(
        {"subject": "Hi", "body": "x", "recipients": ["a@x.com", "b@y.com"]}
    )
    assert calls["mail"]["recipients"] == ["a@x.com", "b@y.com"]


def test_prepare_reminders_passes_through_degraded_message():
    # When remind_fn returns a string (degraded path), the tool surfaces it verbatim.
    deps, _ = _deps(remind_fn=lambda **kw: "There's no one to remind for this event yet.")
    deps.session_store.set_current_event("h1", "ev-3")
    tools = _by_name(build_tools(deps, RequestContext(user_id="h1", role="moderator")))
    out = tools["prepare_reminders"].invoke({})
    assert out == "There's no one to remind for this event yet."


def test_prepare_reminders_default_message_on_success():
    # remind_fn returns None on success (it emitted a card) → tool uses the default prompt.
    deps, _ = _deps(remind_fn=lambda **kw: None)
    deps.session_store.set_current_event("h1", "ev-3")
    tools = _by_name(build_tools(deps, RequestContext(user_id="h1", role="moderator")))
    out = tools["prepare_reminders"].invoke({})
    assert "pick a channel" in out.lower()
