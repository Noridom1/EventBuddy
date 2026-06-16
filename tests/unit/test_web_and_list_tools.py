"""Impl 3 — tool registration + delegation for the new model tools. Tested via `build_tools`
with fake capability closures (no DB/Graph/Tavily), mirroring test_action_tools.py.

Covers: web tools register ONLY when both web closures are wired (else absent); list_my_events
and read_channel_discussion are always present, carry no identity in their schema, and delegate
to their closures with the server-side identity/event from the RequestContext."""
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
    base = dict(
        session_store=_FakeSession(),
        provision_fn=lambda **kw: type("E", (), {"event_id": "ev-1"})(),
        resolve_event_fn=lambda q, **kw: "ev-7",
        remind_fn=lambda **kw: None,
        report_fn=lambda **kw: "report",
        query_tasks_fn=lambda **kw: "tasks",
    )
    base.update(overrides)
    return AgentDeps(**base)


def _by_name(tools):
    return {t.name: t for t in tools}


def test_web_tools_absent_without_closures():
    tools = _by_name(build_tools(_deps(), RequestContext(user_id="u1")))
    assert "web_search" not in tools and "web_fetch" not in tools


def test_web_tools_registered_when_wired():
    deps = _deps(web_search_fn=lambda **kw: "results", web_fetch_fn=lambda **kw: "page")
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1")))
    assert {"web_search", "web_fetch"} <= set(tools)
    assert set(tools["web_search"].args) == {"query"}
    assert set(tools["web_fetch"].args) == {"url"}


def test_web_tools_require_both_closures():
    # Only one wired → still absent (both search + fetch must be present).
    deps = _deps(web_search_fn=lambda **kw: "results")
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1")))
    assert "web_search" not in tools and "web_fetch" not in tools


def test_web_search_delegates():
    calls = {}

    def web_search_fn(**kw):
        calls.update(kw)
        return "search-output"

    deps = _deps(web_search_fn=web_search_fn, web_fetch_fn=lambda **kw: "page")
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1")))
    out = tools["web_search"].invoke({"query": "venues in Da Nang"})
    assert out == "search-output" and calls == {"query": "venues in Da Nang"}


def test_list_my_events_present_and_delegates_with_identity():
    calls = {}

    def list_events_fn(**kw):
        calls.update(kw)
        return "Your events:\n• Launch"

    deps = _deps(list_events_fn=list_events_fn)
    deps.session_store.set_current_event("u1", "ev-3")
    tools = _by_name(build_tools(deps, RequestContext(
        user_id="u1", current_event_id="ev-3")))
    assert "list_my_events" in tools
    assert tools["list_my_events"].args == {}  # no identity args exposed to the model
    out = tools["list_my_events"].invoke({})
    assert out.startswith("Your events:")
    # Impl 18 — delegates the caller's full identity (server-side), not a bare user_id.
    assert set(calls) == {"identity", "current_event_id"}
    assert calls["identity"].teams_user_id == "u1"
    assert calls["current_event_id"] == "ev-3"


def test_read_channel_discussion_delegates_with_focused_event():
    calls = {}

    def read_channel_fn(**kw):
        calls.update(kw)
        return "<external_untrusted_content>...</external_untrusted_content>"

    deps = _deps(read_channel_fn=read_channel_fn)
    tools = _by_name(build_tools(deps, RequestContext(
        user_id="u1", scope="channel", current_event_id="ev-9")))
    assert "read_channel_discussion" in tools
    assert "user_id" not in tools["read_channel_discussion"].args
    tools["read_channel_discussion"].invoke({"limit": 15})
    assert calls == {"user_id": "u1", "event_id": "ev-9", "limit": 15}
