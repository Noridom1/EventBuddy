import pytest

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

    def provision_fn(**kw):
        calls["provision"] = kw
        return type("E", (), {"event_id": "ev-1"})()

    base = dict(
        session_store=_FakeSession(),
        provision_fn=provision_fn,
        resolve_event_fn=lambda q: "ev-7",
        remind_fn=lambda **kw: calls.setdefault("remind", kw),
        report_fn=lambda **kw: "report",
        query_tasks_fn=lambda **kw: "tasks",
    )
    base.update(overrides)
    return AgentDeps(**base), calls


def _by_name(tools):
    return {t.name: t for t in tools}


def test_identity_absent_from_every_tool_schema():
    deps, _ = _deps()
    ctx = RequestContext(user_id="u1", role="host")
    tools = build_tools(deps, ctx)
    for t in tools:
        assert "user_id" not in t.args
        assert "host_user_id" not in t.args


def test_create_event_schema_has_only_model_args():
    deps, _ = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="host")))
    assert set(tools["create_event"].args) == {"name", "member_emails", "objective"}


def test_create_event_invokes_provision_with_context_identity():
    deps, calls = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="leader-9", role="host")))
    out = tools["create_event"].invoke({"name": "X", "member_emails": ["a@x.com"]})
    assert calls["provision"]["host_user_id"] == "leader-9"
    assert calls["provision"]["member_emails"] == ["a@x.com"]
    assert "ev-1" in out


def test_set_focus_event_resolves_and_writes_session():
    deps, _ = _deps()
    ctx = RequestContext(user_id="u1", role="host")
    tools = _by_name(build_tools(deps, ctx))
    out = tools["set_focus_event"].invoke({"event_query": "AI Workshop"})
    assert deps.session_store.get_current_event("u1") == "ev-7"
    assert "AI Workshop" in out


def test_set_focus_event_unknown_returns_not_found_and_no_write():
    deps, _ = _deps(resolve_event_fn=lambda q: None)
    ctx = RequestContext(user_id="u1", role="host")
    tools = _by_name(build_tools(deps, ctx))
    out = tools["set_focus_event"].invoke({"event_query": "Nope"})
    assert "couldn't find" in out.lower()
    assert deps.session_store.get_current_event("u1") is None


def test_list_my_tasks_passes_focused_event():
    deps, _ = _deps(query_tasks_fn=lambda *, user_id, event_id: f"{user_id}:{event_id}")
    deps.session_store.set_current_event("u1", "ev-3")
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="member")))
    assert tools["list_my_tasks"].invoke({}) == "u1:ev-3"


@pytest.mark.parametrize("name", ["list_my_tasks", "generate_report", "get_event_context"])
def test_readonly_tools_take_no_model_args(name):
    deps, _ = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="member")))
    assert tools[name].args == {}


# --- Impl 8: scope-aware members/files threaded from RequestContext -------------------

def test_list_members_passes_scope_and_channel_from_context():
    seen = {}
    deps, _ = _deps(list_members_fn=lambda **kw: seen.update(kw) or "ok")
    ctx = RequestContext(user_id="u1", channel_id="19:chat@thread.v2", scope="group", role="member")
    tools = _by_name(build_tools(deps, ctx))
    assert "list_members" in tools
    assert tools["list_members"].args == {}  # no model-settable args (identity is server-side)
    tools["list_members"].invoke({})
    assert seen["scope"] == "group" and seen["channel_id"] == "19:chat@thread.v2"
    assert "user_id" in seen  # identity injected server-side


def test_file_tools_pass_scope_and_channel_from_context():
    seen_list, seen_read = {}, {}
    deps, _ = _deps(
        list_event_files_fn=lambda **kw: seen_list.update(kw) or "ok",
        read_event_file_fn=lambda **kw: seen_read.update(kw) or "ok",
    )
    ctx = RequestContext(user_id="u1", channel_id="19:chat@thread.v2", scope="personal",
                         role="member")
    tools = _by_name(build_tools(deps, ctx))
    tools["list_event_files"].invoke({})
    tools["read_event_file"].invoke({"link": "https://x/f.docx"})
    assert seen_list["scope"] == "personal" and seen_list["channel_id"] == "19:chat@thread.v2"
    assert seen_read["scope"] == "personal" and seen_read["link"] == "https://x/f.docx"


# --- Phase 1.9: cross-context memory (DM ← event) -------------------------------------

def _ctx_fn(snapshot="Context from event 'X': earlier discussion"):
    calls = []

    def fn(*, user_id, event_id):
        calls.append({"user_id": user_id, "event_id": event_id})
        return snapshot

    fn.calls = calls
    return fn


def test_focus_injects_event_context_in_dm():
    fn = _ctx_fn("Context from event 'Launch': we agreed on Friday.")
    deps, _ = _deps(event_context_fn=fn)
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="host")))
    out = tools["set_focus_event"].invoke({"event_query": "Launch"})
    assert "Focused on 'Launch'." in out
    assert "we agreed on Friday." in out
    assert fn.calls == [{"user_id": "u1", "event_id": "ev-7"}]  # server-resolved id, no model arg


def test_non_member_gets_no_event_context_but_focus_succeeds():
    fn = _ctx_fn("")  # helper returns empty for a non-member
    deps, _ = _deps(event_context_fn=fn)
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="host")))
    out = tools["set_focus_event"].invoke({"event_query": "Launch"})
    assert out == "Focused on 'Launch'."
    assert deps.session_store.get_current_event("u1") == "ev-7"  # focus still set


def test_channel_scope_skips_injection():
    fn = _ctx_fn()
    deps, _ = _deps(event_context_fn=fn)
    ctx = RequestContext(user_id="u1", channel_id="ch1", scope="channel", role="member")
    tools = _by_name(build_tools(deps, ctx))
    out = tools["set_focus_event"].invoke({"event_query": "Launch"})
    assert out == "Focused on 'Launch'."
    assert fn.calls == []  # no cross-context fetch in a channel — the event IS the live window


def test_event_context_tools_never_take_event_arg():
    deps, _ = _deps(event_context_fn=_ctx_fn())
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="host")))
    assert set(tools["set_focus_event"].args) == {"event_query"}  # a name fragment, not an id
    assert tools["get_event_context"].args == {}  # reads the server-resolved focused event


def test_get_event_context_reads_current_event():
    fn = _ctx_fn("Context from event 'X': latest.")
    deps, _ = _deps(event_context_fn=fn)
    deps.session_store.set_current_event("u1", "ev-9")
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="member")))
    out = tools["get_event_context"].invoke({})
    assert "latest." in out
    assert fn.calls == [{"user_id": "u1", "event_id": "ev-9"}]


def test_get_event_context_friendly_when_no_focus():
    deps, _ = _deps(event_context_fn=_ctx_fn())
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="member")))
    out = tools["get_event_context"].invoke({})
    assert "focus" in out.lower()
