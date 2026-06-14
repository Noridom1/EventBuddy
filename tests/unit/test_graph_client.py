from eventbuddy.integrations.graph.client import GraphClient


class _FakeToken:
    def get_token(self):
        return "tok-123"


class _FakeHttp:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, headers=None):
        self.calls.append(("POST", url, json, headers))
        return type("R", (), {"status_code": 201, "json": lambda self=None: {"id": "msg-1"},
                              "raise_for_status": lambda self=None: None})()


def test_send_channel_message_authenticates_and_posts():
    http = _FakeHttp()
    gc = GraphClient(token_provider=_FakeToken(), http=http)
    gc.send_channel_message(team_id="t", channel_id="c", text="hi")
    method, url, body, headers = http.calls[0]
    assert "teams/t/channels/c/messages" in url
    assert headers["Authorization"] == "Bearer tok-123"
    assert body["body"]["content"] == "hi"
