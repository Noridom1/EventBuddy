from fastapi import FastAPI
from fastapi.testclient import TestClient

from eventbuddy.agent.orchestrator import Orchestrator
from eventbuddy.api import dev


class _FakeRunner:
    def __init__(self):
        self.threads = []
        self.resets = []
        self.reset_all_called = 0

    def run(self, text, ctx):
        self.threads.append(ctx.thread_id)
        return f"echo:{text}"

    def reset(self, thread_id):
        self.resets.append(thread_id)

    def reset_all(self):
        self.reset_all_called += 1
        return {"windows": 3, "transcript": 5, "summaries": 2}


class _FakeSession:
    def __init__(self):
        self.current = {}
        self.cleared_all = 0

    def get_current_event(self, user_id):
        return self.current.get(user_id)

    def set_current_event(self, user_id, event_id):
        self.current[user_id] = event_id

    def clear_current_event(self, user_id):
        self.current.pop(user_id, None)

    def clear_all(self):
        n = len(self.current)
        self.current.clear()
        self.cleared_all += 1
        return n


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
    assert r.json() == {"reply": "echo:hello"}  # no `cards` key when none emitted


def test_dev_handle_surfaces_emitted_cards():
    from eventbuddy.bot.turn_artifacts import emit_card

    class _CardRunner(_FakeRunner):
        def run(self, text, ctx):
            emit_card({"type": "AdaptiveCard", "id": "c1"})  # a HITL tool emitting mid-turn
            return "prepared"

    c = _client(_orch_with_runner(_CardRunner()))
    body = c.post("/api/dev/handle", json={"user_id": "u1", "text": "remind"}).json()
    assert body["reply"] == "prepared"
    assert body["cards"][0]["id"] == "c1"


def test_dev_confirm_invokes_confirm_handler():
    orch = _orch_with_runner(_FakeRunner())

    class _Confirm:
        def resolve(self, **kw):
            return f"confirmed:{kw['pending_id']}:{kw['channel']}"

    orch.confirm_handler = _Confirm()
    r = _client(orch).post(
        "/api/dev/confirm",
        json={"pending_id": "p1", "channel": "outlook", "user_id": "u1"},
    )
    assert r.json() == {"reply": "confirmed:p1:outlook"}


def test_dev_confirm_without_handler_reports_cleanly():
    c = _client(_orch_with_runner(_FakeRunner()))  # no confirm_handler attribute set
    r = c.post("/api/dev/confirm", json={"pending_id": "p1"})
    assert "not wired" in r.json()["error"]


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


def test_dev_reset_all_wipes_everyone():
    runner = _FakeRunner()
    orch = _orch_with_runner(runner)
    orch.session.set_current_event("u1", "ev-1")
    r = _client(orch).post("/api/dev/reset", json={"all": True})
    assert r.status_code == 200
    body = r.json()
    assert body["reset"] == "all"
    # per-layer counts surfaced; sessions cleared by the orchestrator, not the runner
    assert body["cleared"] == {"windows": 3, "transcript": 5, "summaries": 2, "sessions": 1}
    assert runner.reset_all_called == 1
    assert orch.session.cleared_all == 1


def test_dev_reset_single_user_only_resets_that_dm():
    runner = _FakeRunner()
    orch = _orch_with_runner(runner)
    r = _client(orch).post("/api/dev/reset", json={"user_id": "u9"})
    assert r.json() == {"reset": "u9"}
    assert runner.resets == ["dm:u9"]  # per-user path, not reset_all
    assert runner.reset_all_called == 0


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
