"""Impl 2 tool wiring: `ingest_event_files` — role gate, focused-event guard, and delegation
to `ingest_fn` with server-side identity (no DB/Graph; same pattern as test_action_tools.py)."""
from eventbuddy.agent.context import RequestContext
from eventbuddy.agent.tools import AgentDeps, build_tools


class _FakeSession:
    def __init__(self):
        self.current = {}

    def set_current_event(self, user_id, event_id):
        self.current[user_id] = event_id

    def get_current_event(self, user_id):
        return self.current.get(user_id)


def _deps():
    calls = {}

    def ingest_fn(**kw):
        calls["ingest"] = kw
        return "📎 Ingested 1 file(s)."

    deps = AgentDeps(
        session_store=_FakeSession(),
        provision_fn=lambda **kw: None,
        resolve_event_fn=lambda q, **kw: None,
        remind_fn=lambda **kw: None,
        report_fn=lambda **kw: "report",
        query_tasks_fn=lambda **kw: "tasks",
        ingest_fn=ingest_fn,
    )
    return deps, calls


def _by_name(tools):
    return {t.name: t for t in tools}


def test_ingest_tool_registered_with_link_only_schema():
    deps, _ = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="moderator")))
    assert "ingest_event_files" in tools
    assert set(tools["ingest_event_files"].args) == {"link"}
    assert "user_id" not in tools["ingest_event_files"].args


def test_ingest_requires_moderator():
    deps, calls = _deps()
    deps.session_store.set_current_event("u1", "ev-3")
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="member")))
    out = tools["ingest_event_files"].invoke({})
    assert "permission" in out.lower()
    assert "ingest" not in calls


def test_ingest_needs_focused_event():
    deps, calls = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="moderator")))
    out = tools["ingest_event_files"].invoke({})
    assert "focus" in out.lower()
    assert "ingest" not in calls


def test_ingest_delegates_with_identity_and_link():
    deps, calls = _deps()
    deps.session_store.set_current_event("u1", "ev-9")
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="host")))
    out = tools["ingest_event_files"].invoke({"link": "https://share/x.xlsx"})
    assert out.startswith("📎")
    assert calls["ingest"] == dict(event_id="ev-9", user_id="u1", url="https://share/x.xlsx")
