"""Impl 8 — scope-aware members + files in group chats / 1-1 DMs.

`list_members` and the chat branches of list_event_files / read_event_file key on the chat id
(the inbound channel_id) and need no focused event. Graph is injected; the channel paths are
covered by test_event_files.py (regression guard there)."""
from eventbuddy.agent import wiring
from eventbuddy.ingestion.parsers import ParsedDoc


def _enable_graph(monkeypatch):
    for k in ("graph_tenant_id", "graph_client_id", "graph_client_secret"):
        monkeypatch.setattr(wiring.settings, k, "set")


class _Graph:
    def __init__(self, *, chat_members=None, chat_files=None, channel_members=None, content=None):
        self._chat_members = chat_members or []
        self._chat_files = chat_files or []
        self._channel_members = channel_members or []
        self._content = content or (b"", "", "")
        self.calls = []

    def list_chat_members(self, chat_id):
        self.calls.append(("chat_members", chat_id))
        return self._chat_members

    def list_channel_members(self, team_id, channel_id):
        self.calls.append(("channel_members", team_id, channel_id))
        return self._channel_members

    def list_chat_files(self, chat_id, limit=50):
        self.calls.append(("chat_files", chat_id))
        return self._chat_files

    def resolve_share_url(self, url):
        self.calls.append(("resolve", url))
        return ("driveShare", "itemShare")

    def get_drive_item_content(self, drive_id, item_id):
        self.calls.append(("download", drive_id, item_id))
        return self._content


# --- list_members --------------------------------------------------------------------------

def test_list_members_group_uses_chat_endpoint(monkeypatch):
    _enable_graph(monkeypatch)
    graph = _Graph(chat_members=[
        {"id": "u1", "display_name": "Ann", "email": "ann@x.com"},
        {"id": "u2", "display_name": "Bo", "email": ""},
    ])
    fn = wiring._build_list_members_fn(graph_factory=lambda: graph)
    out = fn(scope="group", channel_id="19:chat@thread.v2", user_id="u1")
    assert "Ann <ann@x.com>" in out and "• Bo" in out
    assert "external_untrusted_content" in out
    assert graph.calls == [("chat_members", "19:chat@thread.v2")]


def test_list_members_channel_uses_team_endpoint(monkeypatch):
    _enable_graph(monkeypatch)
    graph = _Graph(channel_members=[{"id": "u9", "display_name": "Cy", "email": "cy@x.com"}])
    fn = wiring._build_list_members_fn(graph_factory=lambda: graph)
    out = fn(scope="channel", channel_id="c1", team_id="t1", user_id="u9")
    assert "Cy <cy@x.com>" in out
    assert graph.calls == [("channel_members", "t1", "c1")]


def test_list_members_personal_dm_works(monkeypatch):
    _enable_graph(monkeypatch)
    graph = _Graph(chat_members=[{"id": "u1", "display_name": "Me", "email": "me@x.com"}])
    fn = wiring._build_list_members_fn(graph_factory=lambda: graph)
    out = fn(scope="personal", channel_id="19:dm@thread.v2", user_id="u1")
    assert "Me <me@x.com>" in out


def test_list_members_no_creds_degrades(monkeypatch):
    monkeypatch.setattr(wiring, "_graph_creds", lambda: False)
    called = []
    fn = wiring._build_list_members_fn(graph_factory=lambda: called.append(1))
    out = fn(scope="group", channel_id="c", user_id="u")
    assert "isn't configured" in out.lower()
    assert called == []


def test_list_members_channel_no_team_id_guides(monkeypatch):
    _enable_graph(monkeypatch)
    fn = wiring._build_list_members_fn(graph_factory=lambda: _Graph())
    out = fn(scope="channel", channel_id="c1", team_id=None, user_id="u")
    assert "team" in out.lower()


def test_list_members_graph_error_degrades(monkeypatch):
    _enable_graph(monkeypatch)

    class _Boom(_Graph):
        def list_chat_members(self, chat_id):
            raise RuntimeError("403 forbidden")

    fn = wiring._build_list_members_fn(graph_factory=lambda: _Boom())
    out = fn(scope="group", channel_id="c", user_id="u")
    assert "couldn't" in out.lower() and "external_untrusted_content" not in out


# --- list_event_files (chat branch) --------------------------------------------------------

def test_list_files_group_lists_chat_attachments_no_event(monkeypatch):
    _enable_graph(monkeypatch)
    graph = _Graph(chat_files=[
        {"name": "agenda.docx", "url": "https://x/agenda.docx"},
        {"name": "budget.xlsx", "url": "https://x/budget.xlsx"},
    ])
    fn = wiring._build_list_event_files_fn(graph_factory=lambda: graph)
    out = fn(user_id="u1", event_id=None, scope="group", channel_id="19:chat@thread.v2")
    assert "agenda.docx" in out and "https://x/agenda.docx" in out
    assert "budget.xlsx" in out
    assert "external_untrusted_content" in out
    assert graph.calls == [("chat_files", "19:chat@thread.v2")]


def test_list_files_group_empty(monkeypatch):
    _enable_graph(monkeypatch)
    fn = wiring._build_list_event_files_fn(graph_factory=lambda: _Graph(chat_files=[]))
    out = fn(user_id="u1", event_id=None, scope="group", channel_id="c")
    assert "no files" in out.lower()


def test_list_files_group_no_creds(monkeypatch):
    monkeypatch.setattr(wiring, "_graph_creds", lambda: False)
    fn = wiring._build_list_event_files_fn(graph_factory=lambda: _Graph())
    out = fn(user_id="u1", event_id=None, scope="personal", channel_id="c")
    assert "isn't configured" in out.lower()


# --- read_event_file (chat branch) ---------------------------------------------------------

def test_read_file_group_via_share_link(monkeypatch):
    _enable_graph(monkeypatch)
    monkeypatch.setattr(
        "eventbuddy.ingestion.parsers.parse",
        lambda f, c: ParsedDoc(kind="docx", filename=f, text="Agenda: 1) intro 2) demo"))
    graph = _Graph(content=(b"bytes", "agenda.docx", "application/docx"))
    fn = wiring._build_read_event_file_fn(graph_factory=lambda: graph)
    out = fn(user_id="u1", event_id=None, scope="group",
             channel_id="c", link="https://x/agenda.docx")
    assert "Agenda: 1) intro 2) demo" in out
    assert "external_untrusted_content" in out
    assert ("resolve", "https://x/agenda.docx") in graph.calls


def test_read_file_group_stray_file_id_guides(monkeypatch):
    _enable_graph(monkeypatch)
    fn = wiring._build_read_event_file_fn(graph_factory=lambda: _Graph())
    out = fn(user_id="u1", event_id=None, scope="group", channel_id="c", file_id="f1")
    assert "link" in out.lower()
