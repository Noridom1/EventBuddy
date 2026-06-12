from eventbuddy.agent.context import RequestContext
from eventbuddy.agent.tools import AgentDeps, build_tools


class _FakeSession:
    def __init__(self, current=None):
        self.current = current or {}

    def set_current_event(self, user_id, event_id):
        self.current[user_id] = event_id

    def get_current_event(self, user_id):
        return self.current.get(user_id)


def _deps(calls):
    def provision_fn(**kw):
        calls["provision"] = kw
        return type("E", (), {"event_id": "ev-1"})()

    return AgentDeps(
        session_store=_FakeSession({"m1": "ev-1", "h1": "ev-1"}),
        provision_fn=provision_fn,
        resolve_event_fn=lambda q: "ev-7",
        remind_fn=lambda **kw: calls.setdefault("remind", kw),
        report_fn=lambda **kw: "report",
        query_tasks_fn=lambda **kw: "tasks",
    )


def _tool(deps, ctx, name):
    return {t.name: t for t in build_tools(deps, ctx)}[name]


def test_member_cannot_create_event_and_body_not_called():
    calls = {}
    deps = _deps(calls)
    out = _tool(deps, RequestContext(user_id="m1", role="member"), "create_event").invoke(
        {"name": "X", "member_emails": ["a@x.com"]}
    )
    assert "permission" in out.lower()
    assert "provision" not in calls


def test_host_can_create_event():
    calls = {}
    deps = _deps(calls)
    _tool(deps, RequestContext(user_id="h1", role="host"), "create_event").invoke(
        {"name": "X", "member_emails": ["a@x.com"]}
    )
    assert "provision" in calls


def test_member_cannot_prepare_reminders():
    calls = {}
    deps = _deps(calls)
    out = _tool(deps, RequestContext(user_id="m1", role="member"), "prepare_reminders").invoke({})
    assert "permission" in out.lower()
    assert "remind" not in calls


def test_moderator_can_prepare_reminders():
    calls = {}
    deps = _deps(calls)
    _tool(deps, RequestContext(user_id="h1", role="moderator"), "prepare_reminders").invoke({})
    assert "remind" in calls


def test_readonly_tools_need_no_role():
    calls = {}
    deps = _deps(calls)
    out = _tool(deps, RequestContext(user_id="m1", role="member"), "list_my_tasks").invoke({})
    assert out == "tasks"
