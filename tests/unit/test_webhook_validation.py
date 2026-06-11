from fastapi.testclient import TestClient

from eventbuddy.main import app


def test_graph_webhook_echoes_validation_token():
    client = TestClient(app)
    resp = client.post("/api/webhooks/graph?validationToken=abc123")
    assert resp.status_code == 200
    assert resp.text == "abc123"


def test_graph_webhook_accepts_notification():
    client = TestClient(app)
    resp = client.post("/api/webhooks/graph", json={"value": []})
    assert resp.status_code == 202
