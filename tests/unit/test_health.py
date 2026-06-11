# tests/unit/test_health.py
from fastapi.testclient import TestClient

from eventbuddy.main import app


def test_health_returns_200():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
