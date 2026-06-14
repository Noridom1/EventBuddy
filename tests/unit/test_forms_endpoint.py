from fastapi import FastAPI
from fastapi.testclient import TestClient

from eventbuddy.api import forms


class _Repo:
    def __init__(self):
        self.added = []

    def add(self, event_id, *, respondent_id, raw_payload, sentiment=None, themes=None):
        self.added.append((event_id, respondent_id, raw_payload, sentiment, themes))


class _Analyzer:
    def analyze(self, comment):
        return "positive", ["content"]


def test_ingest_response_stores_with_analysis():
    repo = _Repo()
    forms.ingest_response(
        {"event_id": "ev1", "respondent_id": "ua", "rating": 5, "comment": "Great content"},
        repo=repo, analyzer=_Analyzer())
    event_id, respondent, raw, sentiment, themes = repo.added[0]
    assert event_id == "ev1"
    assert raw["rating"] == 5
    assert sentiment == "positive"
    assert themes == {"tags": ["content"]}


def test_forms_endpoint_acks_202(monkeypatch):
    seen = {}
    monkeypatch.setattr(forms, "_ingest", lambda payload: seen.update(payload))
    app = FastAPI()
    app.include_router(forms.router)
    r = TestClient(app).post("/api/webhooks/forms",
                             json={"event_id": "ev1", "rating": 4, "comment": "ok"})
    assert r.status_code == 202
    assert seen["event_id"] == "ev1"


def test_forms_endpoint_never_5xx_on_failure(monkeypatch):
    def boom(payload):
        raise RuntimeError("db down")

    monkeypatch.setattr(forms, "_ingest", boom)
    app = FastAPI()
    app.include_router(forms.router)
    r = TestClient(app).post("/api/webhooks/forms", json={"event_id": "ev1"})
    assert r.status_code == 202  # webhook must not surface a 5xx
