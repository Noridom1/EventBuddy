"""Impl 3 — the Tavily-backed web client (`integrations/web/client.py`). Verifies search +
extract mapping and the degradation contract (any network error → empty result, never raises,
so a flaky search can't break a conversation turn)."""
from eventbuddy.integrations.web.client import WebSearchClient


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _FakeHttp:
    def __init__(self, payload=None, raise_exc=None):
        self.payload = payload or {}
        self.raise_exc = raise_exc
        self.calls = []

    def post(self, url, json=None):
        self.calls.append((url, json))
        if self.raise_exc:
            raise self.raise_exc
        return _Resp(self.payload)


def test_search_maps_results():
    http = _FakeHttp({"results": [
        {"title": "T1", "url": "https://a", "content": "snippet one"},
        {"title": "T2", "url": "https://b", "content": "snippet two"},
    ]})
    wc = WebSearchClient(api_key="k", http=http)
    out = wc.search("teambuilding venues", max_results=2)
    assert out == [
        {"title": "T1", "url": "https://a", "snippet": "snippet one"},
        {"title": "T2", "url": "https://b", "snippet": "snippet two"},
    ]
    url, body = http.calls[0]
    assert url == "/search" and body["query"] == "teambuilding venues" and body["max_results"] == 2


def test_fetch_extracts_and_truncates():
    long_text = "x" * 10000
    http = _FakeHttp({"results": [{"raw_content": long_text}]})
    wc = WebSearchClient(api_key="k", http=http)
    out = wc.fetch("https://a")
    assert out["url"] == "https://a"
    assert len(out["content"]) <= 6000  # bounded so a fetch can't blow the working window


def test_search_degrades_on_error():
    wc = WebSearchClient(api_key="k", http=_FakeHttp(raise_exc=RuntimeError("network down")))
    assert wc.search("anything") == []  # no raise


def test_fetch_degrades_on_error():
    wc = WebSearchClient(api_key="k", http=_FakeHttp(raise_exc=RuntimeError("boom")))
    assert wc.fetch("https://a") == {}


def test_fetch_empty_results():
    wc = WebSearchClient(api_key="k", http=_FakeHttp({"results": []}))
    assert wc.fetch("https://a") == {}
