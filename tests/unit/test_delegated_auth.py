"""Delegated Graph auth (Plan 13) — the testable core: token provider, the `graph_for()`
selection logic, and the `/me/sendMail` vs `/users/{upn}/sendMail` branch. The Bot Framework
token-service glue (sign-in, on-behalf-of) needs a live Azure Bot and is exercised in-tenant,
not here."""
import pytest

from eventbuddy.agent.wiring import graph_for
from eventbuddy.config import settings
from eventbuddy.integrations.graph.client import GraphClient
from eventbuddy.integrations.graph.delegated import (
    StaticTokenProvider,
    current_graph_token,
    delegated_enabled,
    use_graph_token,
)


def test_static_token_provider_returns_token():
    assert StaticTokenProvider("abc").get_token() == "abc"


def test_static_token_provider_raises_when_empty():
    with pytest.raises(RuntimeError):
        StaticTokenProvider("").get_token()


def test_use_graph_token_scopes_and_resets():
    assert current_graph_token() is None
    with use_graph_token("tok"):
        assert current_graph_token() == "tok"
    assert current_graph_token() is None  # reset on exit


def test_delegated_enabled_reflects_connection_name(monkeypatch):
    monkeypatch.setattr(settings, "graph_oauth_connection_name", "")
    assert delegated_enabled() is False
    monkeypatch.setattr(settings, "graph_oauth_connection_name", "EventBuddyGraph")
    assert delegated_enabled() is True


def test_graph_for_delegated_with_token_is_on_behalf_of_user(monkeypatch):
    monkeypatch.setattr(settings, "graph_oauth_connection_name", "EventBuddyGraph")
    with use_graph_token("user-token"):
        graph = graph_for()
    assert isinstance(graph, GraphClient)
    assert graph._delegated is True
    assert graph._token.get_token() == "user-token"


def test_graph_for_delegated_without_token_returns_none(monkeypatch):
    # IT mandate: delegated configured but user not signed in → NO tenant-wide app fallback.
    monkeypatch.setattr(settings, "graph_oauth_connection_name", "EventBuddyGraph")
    assert current_graph_token() is None
    assert graph_for() is None


def test_signin_needed_flag_toggles():
    from eventbuddy.integrations.graph.delegated import (
        clear_signin_needed,
        mark_signin_needed,
        signin_needed,
    )

    clear_signin_needed()
    assert signin_needed() is False
    mark_signin_needed()
    assert signin_needed() is True
    clear_signin_needed()
    assert signin_needed() is False


def test_graph_for_delegated_without_token_marks_signin_needed(monkeypatch):
    from eventbuddy.integrations.graph.delegated import clear_signin_needed, signin_needed

    monkeypatch.setattr(settings, "graph_oauth_connection_name", "EventBuddyGraph")
    clear_signin_needed()
    assert graph_for() is None
    assert signin_needed() is True  # so the router auto-prompts sign-in


def test_graph_for_with_token_does_not_mark_signin_needed(monkeypatch):
    from eventbuddy.integrations.graph.delegated import clear_signin_needed, signin_needed

    monkeypatch.setattr(settings, "graph_oauth_connection_name", "EventBuddyGraph")
    clear_signin_needed()
    with use_graph_token("user-token"):
        graph_for()
    assert signin_needed() is False


def test_graph_for_app_only_fallback_when_no_connection(monkeypatch):
    monkeypatch.setattr(settings, "graph_oauth_connection_name", "")
    monkeypatch.setattr(settings, "graph_tenant_id", "t")
    monkeypatch.setattr(settings, "graph_client_id", "c")
    monkeypatch.setattr(settings, "graph_client_secret", "s")

    class _FakeMsal:
        def get_token(self):
            return "app-token"

    monkeypatch.setattr("eventbuddy.integrations.graph.token.MsalTokenProvider", _FakeMsal)
    graph = graph_for()
    assert isinstance(graph, GraphClient)
    assert graph._delegated is False


def test_graph_for_returns_none_when_nothing_configured(monkeypatch):
    monkeypatch.setattr(settings, "graph_oauth_connection_name", "")
    monkeypatch.setattr(settings, "graph_tenant_id", "")
    monkeypatch.setattr(settings, "graph_client_id", "")
    monkeypatch.setattr(settings, "graph_client_secret", "")
    assert graph_for() is None


class _FakeResp:
    def raise_for_status(self):
        return None


class _FakeHttp:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResp()


def test_send_mail_delegated_uses_me_sendmail():
    http = _FakeHttp()
    graph = GraphClient(StaticTokenProvider("tok"), http=http, delegated=True)
    graph.send_mail(subject="Hi", body_html="<p>hi</p>", to=["a@x.com"])
    assert http.calls[0]["url"] == "/me/sendMail"


def test_send_mail_app_only_uses_users_sendmail():
    http = _FakeHttp()
    graph = GraphClient(StaticTokenProvider("tok"), http=http, sender="bot@corp.com")
    graph.send_mail(subject="Hi", body_html="<p>hi</p>", to=["a@x.com"])
    assert http.calls[0]["url"] == "/users/bot%40corp.com/sendMail"


def test_send_mail_app_only_requires_sender():
    http = _FakeHttp()
    graph = GraphClient(StaticTokenProvider("tok"), http=http, sender="")
    with pytest.raises(ValueError):
        graph.send_mail(subject="Hi", body_html="<p>hi</p>", to=["a@x.com"])


def test_resolve_host_token_app_only_is_ok_without_token(monkeypatch):
    from eventbuddy.scheduler.jobs import _resolve_host_token

    monkeypatch.setattr(settings, "graph_oauth_connection_name", "")
    assert _resolve_host_token("host-1") == (None, "ok")  # app-only path: graph_for uses creds


def test_resolve_host_token_delegated_without_token_needs_reauth(monkeypatch):
    from eventbuddy.scheduler import jobs

    monkeypatch.setattr(settings, "graph_oauth_connection_name", "EventBuddyGraph")
    monkeypatch.setattr(
        "eventbuddy.integrations.graph.delegated.acquire_graph_token_for_user",
        lambda *a, **k: None,
    )
    assert jobs._resolve_host_token("host-1") == (None, "reauth")


class _FakeFrom:
    id = "user-1"


class _FakeActivity:
    from_property = _FakeFrom()
    channel_id = "msteams"


class _FakeUserTokenClient:
    def __init__(self):
        self.calls = []

    async def sign_out_user(self, user_id, connection, channel_id):
        self.calls.append((user_id, connection, channel_id))


class _FakeTurn:
    def __init__(self, client=None, adapter=None):
        self.activity = _FakeActivity()
        self.turn_state = {"UserTokenClient": client} if client else {}
        self.adapter = adapter


@pytest.mark.asyncio
async def test_sign_out_user_noop_when_delegated_disabled(monkeypatch):
    from eventbuddy.integrations.graph.delegated import sign_out_user

    monkeypatch.setattr(settings, "graph_oauth_connection_name", "")
    assert await sign_out_user(_FakeTurn(client=_FakeUserTokenClient())) is False


@pytest.mark.asyncio
async def test_sign_out_user_uses_user_token_client(monkeypatch):
    from eventbuddy.integrations.graph.delegated import sign_out_user

    monkeypatch.setattr(settings, "graph_oauth_connection_name", "EventBuddyGraph")
    client = _FakeUserTokenClient()
    assert await sign_out_user(_FakeTurn(client=client)) is True
    assert client.calls == [("user-1", "EventBuddyGraph", "msteams")]


@pytest.mark.asyncio
async def test_sign_out_user_degrades_when_no_client_or_adapter(monkeypatch):
    from eventbuddy.integrations.graph.delegated import sign_out_user

    monkeypatch.setattr(settings, "graph_oauth_connection_name", "EventBuddyGraph")
    assert await sign_out_user(_FakeTurn()) is False


def _fake_jwt(claims: dict) -> str:
    import base64
    import json

    def seg(d):
        raw = json.dumps(d).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{seg({'alg': 'none'})}.{seg(claims)}.sig"


def test_token_scopes_extracts_scp_claim():
    from eventbuddy.integrations.graph.delegated import token_scopes

    token = _fake_jwt({"scp": "Chat.Create User.ReadBasic.All openid"})
    assert token_scopes(token) == "Chat.Create User.ReadBasic.All openid"


def test_token_scopes_returns_none_for_missing_or_malformed():
    from eventbuddy.integrations.graph.delegated import token_scopes

    assert token_scopes(None) is None
    assert token_scopes("") is None
    assert token_scopes("not-a-jwt") is None
    assert token_scopes(_fake_jwt({"aud": "graph"})) is None  # no scp claim
