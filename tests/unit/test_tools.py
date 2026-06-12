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


@pytest.mark.parametrize("name", ["list_my_tasks", "generate_report"])
def test_readonly_tools_take_no_model_args(name):
    deps, _ = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="member")))
    assert tools[name].args == {}
