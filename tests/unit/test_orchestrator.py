from eventbuddy.agent.orchestrator import Orchestrator


class _Session:
    def __init__(self): self.current = None
    def get_current_event(self, u): return self.current
    def set_current_event(self, u, e): self.current = e


def test_create_event_routes_to_provisioning():
    calls = {}
    deps = _deps(provisioning=lambda **kw: calls.update(kw) or type("E", (), {"event_id": "ev1"})())
    orch = Orchestrator(**deps)
    reply = orch.handle(user_id="u1", channel_id=None,
                        text="create event 'AI Workshop' members: a@x.com")
    assert calls["name"] == "AI Workshop"
    assert "AI Workshop" in reply


def test_context_switch_sets_session():
    sess = _Session()
    deps = _deps(session=sess, resolve_event=lambda q: "ev-42")
    orch = Orchestrator(**deps)
    orch.handle(user_id="u1", channel_id=None, text="focus on AI Workshop")
    assert sess.current == "ev-42"


def _deps(provisioning=None, session=None, resolve_event=None):
    return {
        "session_store": session or _Session(),
        "provision_fn": provisioning or (lambda **kw: type("E", (), {"event_id": "x"})()),
        "resolve_event_fn": resolve_event or (lambda q: "ev-0"),
        "remind_fn": lambda **kw: None,
        "report_fn": lambda **kw: "report-done",
        "query_tasks_fn": lambda **kw: "you have 2 tasks",
    }
