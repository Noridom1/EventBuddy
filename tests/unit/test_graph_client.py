import pytest

from eventbuddy.config import settings
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


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected raise for status {self.status_code}")


class _RoutedHttp:
    """GET/POST stub routed by URL substring → canned _Resp."""

    def __init__(self, get_routes=None, post_routes=None):
        self.get_routes = get_routes or {}
        self.post_routes = post_routes or {}
        self.get_calls = []
        self.post_calls = []

    def get(self, url, headers=None):
        self.get_calls.append(url)
        for frag, resp in self.get_routes.items():
            if frag in url:
                return resp
        return _Resp(404, {})

    def post(self, url, json=None, headers=None):
        self.post_calls.append((url, json))
        for frag, resp in self.post_routes.items():
            if frag in url:
                return resp
        return _Resp(404, {})


def test_resolve_user_by_alias_uses_mailnickname_filter():
    http = _RoutedHttp(get_routes={
        "$filter": _Resp(200, {"value": [
            {"id": "u-1", "displayName": "Phuc", "userPrincipalName": "phucnlt2@vng.com.vn"}]}),
    })
    gc = GraphClient(token_provider=_FakeToken(), http=http)
    user = gc.resolve_user("phucnlt2")
    assert user == {"id": "u-1", "display_name": "Phuc", "upn": "phucnlt2@vng.com.vn"}
    assert any("mailNickname" in u for u in http.get_calls)


def test_resolve_user_by_email_uses_direct_lookup():
    http = _RoutedHttp(get_routes={
        "/users/": _Resp(200, {
            "id": "u-2", "displayName": "Alice", "userPrincipalName": "alice@x.com"}),
    })
    gc = GraphClient(token_provider=_FakeToken(), http=http)
    user = gc.resolve_user("alice@x.com")
    assert user == {"id": "u-2", "display_name": "Alice", "upn": "alice@x.com"}


def test_resolve_user_miss_returns_none():
    http = _RoutedHttp(get_routes={"$filter": _Resp(200, {"value": []})})
    gc = GraphClient(token_provider=_FakeToken(), http=http)
    assert gc.resolve_user("ghost") is None


def test_resolve_user_by_alias_prefers_direct_read(monkeypatch):
    # A bare alias resolves via a direct /users/{alias}@{domain} read — NO directory
    # enumeration ($filter), which the tenant may deny (403). The "/users/" route matches the
    # direct read only ("/users?$filter" has no trailing slash).
    monkeypatch.setattr(settings, "corp_email_domain", "vng.com.vn")
    http = _RoutedHttp(get_routes={
        "/users/": _Resp(200, {
            "id": "u-3", "displayName": "Anh", "userPrincipalName": "anhpn8@vng.com.vn"}),
    })
    gc = GraphClient(token_provider=_FakeToken(), http=http)
    user = gc.resolve_user("anhpn8")
    assert user == {"id": "u-3", "display_name": "Anh", "upn": "anhpn8@vng.com.vn"}
    assert not any("$filter" in u for u in http.get_calls)  # enumeration avoided


def test_resolve_user_falls_back_to_enumeration_when_direct_read_misses(monkeypatch):
    # Direct read 404s (no "/users/" route) → fall back to the $filter enumeration.
    monkeypatch.setattr(settings, "corp_email_domain", "vng.com.vn")
    http = _RoutedHttp(get_routes={
        "$filter": _Resp(200, {"value": [
            {"id": "u-4", "displayName": "Lam", "userPrincipalName": "lamtt7@vng.com.vn"}]}),
    })
    gc = GraphClient(token_provider=_FakeToken(), http=http)
    user = gc.resolve_user("lamtt7")
    assert user["id"] == "u-4"
    assert any("mailNickname" in u for u in http.get_calls)


def test_resolve_user_propagates_enumeration_denial(monkeypatch):
    # Direct read misses AND enumeration is denied → the error propagates so the caller can
    # surface a clear "no permission" message (vs. a misleading "not found").
    monkeypatch.setattr(settings, "corp_email_domain", "vng.com.vn")
    http = _RoutedHttp(get_routes={"$filter": _Resp(403, {})})
    gc = GraphClient(token_provider=_FakeToken(), http=http)
    with pytest.raises(Exception):  # noqa: B017 — stub raises on raise_for_status(403)
        gc.resolve_user("anhpn8")


def test_create_one_on_one_chat_binds_both_members():
    http = _RoutedHttp(
        get_routes={"/me": _Resp(200, {"id": "me-1"})},
        post_routes={"/chats": _Resp(201, {"id": "chat-9"})},
    )
    gc = GraphClient(token_provider=_FakeToken(), http=http)
    chat_id = gc.create_one_on_one_chat("u-7")
    assert chat_id == "chat-9"
    _url, body = http.post_calls[0]
    assert body["chatType"] == "oneOnOne"
    binds = [m["user@odata.bind"] for m in body["members"]]
    assert any("me-1" in b for b in binds) and any("u-7" in b for b in binds)
