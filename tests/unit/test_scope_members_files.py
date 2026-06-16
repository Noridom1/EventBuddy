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

class _Row:
    """A catalog row stand-in (what ChatFileCatalog.sync yields)."""
    def __init__(self, filename, summary=None, doc_type=None):
        self.filename, self.summary, self.doc_type = filename, summary, doc_type


class _MatchResult:
    def __init__(self, exact=None, candidates=None):
        self.exact, self.candidates = exact, candidates or []


class _FakeCatalog:
    """Stands in for ChatFileCatalog — records the sync scope and returns canned rows + a canned
    match result (Impl 9)."""
    def __init__(self, rows=None, match=None):
        self.rows = rows or []
        self._match = match or _MatchResult()
        self.synced = []
        self.matched = []

    def sync(self, chat_id, *, scope, attachments=None, graph=None):
        self.synced.append((chat_id, scope, graph is not None))
        return self.rows

    def match(self, chat_id, query):
        self.matched.append((chat_id, query))
        return self._match


def test_list_files_group_lists_chat_files_from_catalog_no_event(monkeypatch):
    _enable_graph(monkeypatch)
    monkeypatch.setattr(wiring, "graph_for", lambda *a, **k: object())  # a signed-in client
    catalog = _FakeCatalog(rows=[
        _Row("agenda.docx", "The event agenda.", "agenda"),
        _Row("budget.xlsx", "Cost breakdown.", "budget"),
    ])
    fn = wiring._build_list_event_files_fn(catalog=catalog)
    out = fn(user_id="u1", event_id=None, scope="group", channel_id="19:chat@thread.v2")
    assert "agenda.docx" in out and "The event agenda." in out
    assert "budget.xlsx" in out
    assert "external_untrusted_content" in out
    # Group scope syncs with a Graph client (message scan); the chat id is the key.
    assert catalog.synced == [("19:chat@thread.v2", "group", True)]


def test_list_files_personal_dm_never_scans_graph(monkeypatch):
    """A 1-1 DM has no Graph chat — sync must be attachment-only (graph=None), never /chats."""
    _enable_graph(monkeypatch)
    catalog = _FakeCatalog(rows=[_Row("notes.docx", "Some notes.", "other")])
    fn = wiring._build_list_event_files_fn(catalog=catalog)
    out = fn(user_id="u1", event_id=None, scope="personal", channel_id="a:1Wx7", attachments=[])
    assert "notes.docx" in out
    assert catalog.synced == [("a:1Wx7", "personal", False)]  # graph is None in a DM


def test_list_files_group_empty(monkeypatch):
    _enable_graph(monkeypatch)
    fn = wiring._build_list_event_files_fn(catalog=_FakeCatalog(rows=[]))
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
    fn = wiring._build_read_event_file_fn(graph_factory=lambda: _Graph(),
                                          catalog=_FakeCatalog())
    out = fn(user_id="u1", event_id=None, scope="group", channel_id="c", file_id="f1")
    assert "name it" in out.lower() or "link" in out.lower()


class _CatRow:
    def __init__(self, filename, share_url="https://x/f", drive_item_id="i", summary=None):
        self.filename, self.share_url = filename, share_url
        self.drive_item_id, self.summary, self.doc_type = drive_item_id, summary, None


def test_read_file_chat_prefers_current_attachment(monkeypatch):
    """A file shared this turn is read directly — no catalog match, no Graph chat scan."""
    _enable_graph(monkeypatch)
    monkeypatch.setattr(wiring, "_download_uploaded_file", lambda atts: ("up.csv", b"x,y"))
    monkeypatch.setattr("eventbuddy.ingestion.parsers.parse",
                        lambda f, c: ParsedDoc(kind="csv", filename=f, text="x,y\n1,2"))
    catalog = _FakeCatalog()
    fn = wiring._build_read_event_file_fn(catalog=catalog)
    out = fn(user_id="u1", event_id=None, scope="personal", channel_id="a:dm",
             attachments=[{"name": "up.csv", "content_url": "https://x/up"}])
    assert "x,y" in out
    assert catalog.matched == []  # current attachment wins; never consulted the catalog


def test_read_file_chat_resolves_by_name(monkeypatch):
    _enable_graph(monkeypatch)
    monkeypatch.setattr(wiring, "_read_share_url", lambda url: ("agenda.docx", b"bytes"))
    monkeypatch.setattr("eventbuddy.ingestion.parsers.parse",
                        lambda f, c: ParsedDoc(kind="docx", filename=f, text="Agenda: demo"))
    catalog = _FakeCatalog(match=_MatchResult(exact=_CatRow("agenda.docx")))
    fn = wiring._build_read_event_file_fn(catalog=catalog)
    out = fn(user_id="u1", event_id=None, scope="group", channel_id="19:g",
             link="the agenda")  # a name, not a URL
    assert "Agenda: demo" in out and "external_untrusted_content" in out
    assert catalog.matched == [("19:g", "the agenda")]


def test_read_file_chat_ambiguous_asks_and_emits_card(monkeypatch):
    _enable_graph(monkeypatch)
    from eventbuddy.bot.turn_artifacts import begin_artifacts, end_artifacts

    class _Pending:
        def __init__(self):
            self.put_payload = None

        def put(self, payload):
            self.put_payload = payload
            return "pend-1"

    pending = _Pending()
    catalog = _FakeCatalog(match=_MatchResult(candidates=[
        _CatRow("Master Plan v1.docx"), _CatRow("Master Plan v4.docx")]))
    fn = wiring._build_read_event_file_fn(catalog=catalog, pending_store=pending)
    artifacts, token = begin_artifacts()
    try:
        out = fn(user_id="u1", event_id=None, scope="group", channel_id="19:g",
                 link="master plan")
    finally:
        end_artifacts(token)
    assert "Master Plan v1.docx" in out and "Master Plan v4.docx" in out
    # A picker card was emitted and a pending payload stashed (the candidate set, server-side).
    assert len(artifacts.cards) == 1
    assert artifacts.cards[0]["actions"][0]["data"]["action"] == "read_files"
    assert pending.put_payload["type"] == "read_files"
    assert {c["filename"] for c in pending.put_payload["candidates"]} == {
        "Master Plan v1.docx", "Master Plan v4.docx"}
