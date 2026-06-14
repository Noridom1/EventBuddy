"""Impl 3 — GraphClient.list_channel_messages (brainstorm source). Verifies the Graph call
shape, HTML stripping, and that system/empty messages are dropped."""
from eventbuddy.integrations.graph.client import GraphClient, _strip_html


class _FakeToken:
    def get_token(self):
        return "tok"


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _FakeHttp:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def get(self, url, headers=None):
        self.calls.append(url)
        return _Resp(self._payload)


def _http_returning(payload):
    return _FakeHttp(payload)


def test_strip_html_collapses_tags_and_entities():
    assert _strip_html("<p>Hello&nbsp;<b>world</b> &amp; more</p>") == "Hello world & more"


def test_list_channel_messages_parses_and_filters():
    payload = {"value": [
        {"messageType": "message", "from": {"user": {"displayName": "Alice"}},
         "body": {"content": "<p>Let's do a hackathon</p>"},
         "createdDateTime": "2026-06-14T10:00:00Z"},
        {"messageType": "systemEventMessage", "from": None,
         "body": {"content": "Alice added Bob"}},  # system → dropped
        {"messageType": "message", "from": {"user": {"displayName": "Bob"}},
         "body": {"content": "   "}},  # empty after strip → dropped
        {"messageType": "message", "from": {"user": {"displayName": "Carol"}},
         "body": {"content": "<div>Venue ideas?</div>"}},
    ]}
    gc = GraphClient(token_provider=_FakeToken(), http=_http_returning(payload))
    out = gc.list_channel_messages(team_id="t", channel_id="c", limit=10)
    assert out == [
        {"author": "Alice", "text": "Let's do a hackathon", "created": "2026-06-14T10:00:00Z"},
        {"author": "Carol", "text": "Venue ideas?", "created": None},
    ]


def test_list_channel_messages_url_includes_team_and_top():
    http = _http_returning({"value": []})
    gc = GraphClient(token_provider=_FakeToken(), http=http)
    gc.list_channel_messages(team_id="team-9", channel_id="chan-1", limit=5)
    assert "teams/team-9/channels/chan-1/messages" in http.calls[0]
    assert "$top=5" in http.calls[0]
