import pytest

from eventbuddy.integrations.graph.client import GraphClient


class _FakeResp:
    def raise_for_status(self):
        return None


class _FakeHttp:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, headers=None):
        self.calls.append((url, json, headers))
        return _FakeResp()


class _FakeToken:
    def get_token(self):
        return "tok"


def test_send_mail_posts_as_configured_sender():
    http = _FakeHttp()
    client = GraphClient(_FakeToken(), http=http, sender="eventbuddy@corp.com")
    client.send_mail("Hi", "<p>body</p>", ["a@corp.com", "b@corp.com"])

    url, payload, _ = http.calls[0]
    assert url == "/users/eventbuddy%40corp.com/sendMail"
    msg = payload["message"]
    assert msg["subject"] == "Hi"
    assert msg["body"] == {"contentType": "HTML", "content": "<p>body</p>"}
    assert [r["emailAddress"]["address"] for r in msg["toRecipients"]] == [
        "a@corp.com",
        "b@corp.com",
    ]


def test_send_mail_without_sender_fails_loud():
    http = _FakeHttp()
    client = GraphClient(_FakeToken(), http=http, sender="")
    with pytest.raises(ValueError, match="GRAPH_SENDER_UPN"):
        client.send_mail("Hi", "<p>body</p>", ["a@corp.com"])
    assert http.calls == []  # no Graph call attempted
