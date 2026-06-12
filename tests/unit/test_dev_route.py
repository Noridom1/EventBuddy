from fastapi import FastAPI
from fastapi.testclient import TestClient

from eventbuddy.api import dev


def _fake_graph(reply):
    return type("G", (), {"invoke": lambda self, s: {"reply": reply}})()


def test_dev_handle_returns_routed_reply():
    app = FastAPI()
    app.include_router(dev.router)
    app.dependency_overrides[dev.get_graph] = lambda: _fake_graph("Hi!")
    c = TestClient(app)
    r = c.post("/api/dev/handle", json={"user_id": "u1", "text": "hello"})
    assert r.status_code == 200
    assert r.json() == {"reply": "Hi!"}


def test_dev_handle_reports_errors_cleanly():
    app = FastAPI()
    app.include_router(dev.router)

    class _Boom:
        def invoke(self, s):
            raise RuntimeError("no DB")

    app.dependency_overrides[dev.get_graph] = lambda: _Boom()
    c = TestClient(app)
    r = c.post("/api/dev/handle", json={"text": "create event 'X' members: a@x.com"})
    assert r.status_code == 200
    assert "no DB" in r.json()["error"]


def test_dev_route_disabled_by_default():
    from eventbuddy.main import create_app
    c = TestClient(create_app())
    assert c.post("/api/dev/handle", json={"text": "hi"}).status_code == 404
