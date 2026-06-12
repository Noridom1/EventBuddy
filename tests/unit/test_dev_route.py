from fastapi import FastAPI
from fastapi.testclient import TestClient

from eventbuddy.agent.orchestrator import Orchestrator
from eventbuddy.api import dev


class _FakeRunner:
    def __init__(self):
        self.threads = []
        self.resets = []

    def run(self, text, ctx):
        self.threads.append(ctx.thread_id)
        return f"echo:{text}"

    def reset(self, thread_id):
        self.resets.append(thread_id)


class _FakeSession:
    def __init__(self):
        self.current = {}

    def get_current_event(self, user_id):
        return self.current.get(user_id)

    def set_current_event(self, user_id, event_id):
        self.current[user_id] = event_id

    def clear_current_event(self, user_id):
        self.current.pop(user_id, None)


def _orch_with_runner(runner):
    return Orchestrator(
        session_store=_FakeSession(),
        provision_fn=lambda **kw: None,
        resolve_event_fn=lambda q: None,
        remind_fn=lambda **kw: None,
        report_fn=lambda **kw: "report",
        query_tasks_fn=lambda **kw: "tasks",
        runner=runner,
    )


def _client(orch):
    app = FastAPI()
    app.include_router(dev.router)
    app.dependency_overrides[dev.get_orchestrator] = lambda: orch
    return TestClient(app)


def test_dev_handle_returns_routed_reply():
    c = _client(_orch_with_runner(_FakeRunner()))
    r = c.post("/api/dev/handle", json={"user_id": "u1", "text": "hello"})
    assert r.status_code == 200
    assert r.json() == {"reply": "echo:hello"}


def test_multi_turn_keeps_same_dm_thread():
    runner = _FakeRunner()
    c = _client(_orch_with_runner(runner))
    c.post("/api/dev/handle", json={"user_id": "u1", "text": "first"})
    c.post("/api/dev/handle", json={"user_id": "u1", "text": "second"})
    assert runner.threads == ["dm:u1", "dm:u1"]  # same DM thread across turns


def test_reset_clears_thread_before_handling():
    runner = _FakeRunner()
    c = _client(_orch_with_runner(runner))
    r = c.post("/api/dev/handle", json={"user_id": "u1", "text": "fresh", "reset": True})
    assert r.status_code == 200
    assert runner.resets == ["dm:u1"]


class _RaisingOrch:
    def handle(self, **kw):
        raise RuntimeError("no DB")


def test_dev_handle_reports_errors_cleanly():
    # A hard error (not a runner failure, which would degrade to regex) is surfaced as JSON.
    c = _client(_RaisingOrch())
    r = c.post("/api/dev/handle", json={"text": "hi"})
    assert r.status_code == 200
    assert "no DB" in r.json()["error"]


def test_dev_route_disabled_by_default(monkeypatch):
    from eventbuddy import main
    monkeypatch.setattr(main.settings, "dev_routes_enabled", False)
    c = TestClient(main.create_app())
    assert c.post("/api/dev/handle", json={"text": "hi"}).status_code == 404
