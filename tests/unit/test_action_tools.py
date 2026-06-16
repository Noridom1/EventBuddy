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
        resolve_event_fn=lambda q, **kw: "ev-7",
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


def test_update_task_schema_exposes_query_status_due_and_note():
    deps, _ = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="member")))
    assert set(tools["update_task"].args) == {"task_query", "status", "due_date", "note"}


def test_create_task_registered_and_hides_identity():
    deps, _ = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="member")))
    assert "create_task" in tools
    assert set(tools["create_task"].args) == {
        "task_name", "assignee", "due_date", "status", "note"}
    assert "user_id" not in tools["create_task"].args
    assert "identity" not in tools["create_task"].args


def test_create_task_needs_focused_event():
    calls = {}
    deps, _ = _deps(create_task_fn=lambda **kw: calls.setdefault("create", kw) or "made")
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="member")))
    out = tools["create_task"].invoke({"task_name": "Send thanks"})
    assert "focus" in out.lower()
    assert "create" not in calls


def test_create_task_delegates_with_context_identity_any_member():
    captured = {}
    deps, _ = _deps(create_task_fn=lambda **kw: captured.update(kw) or "made")
    deps.session_store.set_current_event("u1", "ev-3")
    # `member` (not moderator) — any member may create tasks.
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="member")))
    out = tools["create_task"].invoke({
        "task_name": "Send thanks", "assignee": "tho", "due_date": "2026-06-20",
        "status": "todo", "note": "rescheduled",
    })
    assert out == "made"
    assert captured["identity"].teams_user_id == "u1"
    assert captured["event_id"] == "ev-3"
    assert captured["task_name"] == "Send thanks" and captured["assignee"] == "tho"
    assert captured["due_date"] == "2026-06-20" and captured["note"] == "rescheduled"
    # identity is server-built, never a model arg
    assert "user_id" not in captured


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
        # Impl 18 — the caller's identity (None here, ctx carries no aad/email) rides along so
        # the host enroll + roster sync can recognize them across contexts.
        "aad_object_id": None, "email": None,
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
    # Impl 18 — update_task delegates the caller's identity (server-side), not a bare user_id.
    update = calls["update"]
    assert update["identity"].teams_user_id == "u1"
    assert update["role"] == "moderator" and update["event_id"] == "ev-3"
    assert update["task_query"] == "slides" and update["status"] == "done"


def test_sync_event_members_delegates_with_scope_and_identity():
    seen = {}

    def sync_members_fn(**kw):
        seen.update(kw)
        return {"ok": True, "added": ["Alice", "Bob"], "already": 1, "skipped": 0}

    deps, _ = _deps(sync_members_fn=sync_members_fn)
    ctx = RequestContext(user_id="u1", aad_object_id="AAD-1", channel_id="conv-1",
                         team_id="team-9", scope="group", role="moderator",
                         current_event_id="ev-3")
    tools = _by_name(build_tools(deps, ctx))
    assert tools["sync_event_members"].args == {}  # no model-settable args
    out = tools["sync_event_members"].invoke({})
    assert "Added 2 member(s)" in out and "Alice, Bob" in out
    assert seen["event_id"] == "ev-3" and seen["scope"] == "group"
    assert seen["channel_id"] == "conv-1" and seen["team_id"] == "team-9"
    assert seen["actor_identity"].aad_object_id == "AAD-1"


def test_sync_event_members_needs_focused_event():
    calls = {}
    deps, _ = _deps(sync_members_fn=lambda **kw: calls.update(kw) or {"ok": True, "added": []})
    ctx = RequestContext(user_id="u1", channel_id="conv-1", scope="group", role="moderator")
    tools = _by_name(build_tools(deps, ctx))
    out = tools["sync_event_members"].invoke({})
    assert "isn't set up for an event" in out and not calls  # closure not called


def test_sync_event_members_blocked_in_dm():
    calls = {}
    deps, _ = _deps(sync_members_fn=lambda **kw: calls.update(kw))
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", scope="personal",
                                                      role="host", current_event_id="ev-3")))
    out = tools["sync_event_members"].invoke({})
    assert "group" in out.lower() and not calls


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


# --- generic send tools (send_email / send_teams_message) ----------------------------------

def test_generic_send_tools_registered_with_identity_absent():
    deps, _ = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="member")))
    assert {"send_email", "send_teams_message"} <= set(tools)
    assert set(tools["send_email"].args) == {"subject", "body", "recipients"}
    assert set(tools["send_teams_message"].args) == {"recipients", "message", "group"}


def test_send_email_callable_by_member_and_delegates():
    calls = {}
    deps, _ = _deps(send_email_fn=lambda **kw: calls.update(kw) or "drafted")
    # A plain member — no role gate on the generic tools.
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="member")))
    out = tools["send_email"].invoke(
        {"subject": "Hi", "body": "x", "recipients": "phucnlt2, a@x.com"})
    assert out == "drafted"
    # The tool coerces a delimited string to a list; alias expansion happens in the closure.
    assert calls == {"user_id": "u1", "subject": "Hi", "body": "x",
                     "recipients": ["phucnlt2", "a@x.com"]}


def test_send_teams_message_callable_by_member_and_delegates():
    calls = {}
    deps, _ = _deps(send_teams_message_fn=lambda **kw: calls.update(kw) or "drafted")
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="member")))
    out = tools["send_teams_message"].invoke(
        {"recipients": "phucnlt2", "message": "standup at 10"})
    assert out == "drafted"
    # A single string is coerced to a one-item list before reaching the closure; `group`
    # defaults to "" when the model omits it.
    assert calls == {"user_id": "u1", "recipients": ["phucnlt2"],
                     "message": "standup at 10", "group": ""}


def test_send_teams_message_coerces_delimited_string_to_list():
    calls = {}
    deps, _ = _deps(send_teams_message_fn=lambda **kw: calls.update(kw) or "drafted")
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="member")))
    out = tools["send_teams_message"].invoke(
        {"recipients": "anhpn8, lamtt7; phucnlt2", "message": "hi"})
    assert out == "drafted"
    assert calls["recipients"] == ["anhpn8", "lamtt7", "phucnlt2"]


def test_send_teams_message_passes_group_label_through():
    # Impl 10 — the agent's `group` label reaches the closure verbatim (it decides merge/separate).
    calls = {}
    deps, _ = _deps(send_teams_message_fn=lambda **kw: calls.update(kw) or "drafted")
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="member")))
    out = tools["send_teams_message"].invoke(
        {"recipients": "phucnlt2", "message": "your task is due", "group": "task-update"})
    assert out == "drafted"
    assert calls["group"] == "task-update"
