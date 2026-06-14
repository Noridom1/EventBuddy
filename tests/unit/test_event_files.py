"""Impl 5, Parts 4-5 — list_event_files + read_event_file wiring closures.

Read-only, membership-gated browse + on-demand read of the focused event channel's files.
Graph is injected; `session_scope` is sqlite-redirected (same pattern as test_brainstorm.py).
Text files return parsed text; images route to the vision model; everything degrades cleanly."""
import contextlib

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from eventbuddy.agent import wiring
from eventbuddy.domain.models import Document, Event, EventMember
from eventbuddy.ingestion.parsers import ParsedDoc


def _factory_with(event_kwargs, members=(), documents=()):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    for model in (Event, EventMember, Document):
        model.__table__.create(engine)
    Local = sessionmaker(bind=engine, expire_on_commit=False)
    with Local() as s:
        s.add(Event(**event_kwargs))
        for m in members:
            s.add(EventMember(event_id=event_kwargs["event_id"], **m))
        for d in documents:
            s.add(Document(event_id=event_kwargs["event_id"], **d))
        s.commit()

    @contextlib.contextmanager
    def factory():
        s = Local()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    return factory, Local


class _Graph:
    def __init__(self, children=None, content=(b"", "", "")):
        self._children = children or []
        self._content = content
        self.downloaded = []

    def get_channel_files_folder(self, team_id, channel_id):
        return ("drive1", "folder1")

    def list_children(self, drive_id, item_id):
        return self._children

    def get_drive_item_content(self, drive_id, item_id):
        self.downloaded.append((drive_id, item_id))
        return self._content

    def resolve_share_url(self, url):
        return ("driveShare", "itemShare")


def _enable_graph(monkeypatch):
    for k in ("graph_tenant_id", "graph_client_id", "graph_client_secret"):
        monkeypatch.setattr(wiring.settings, k, "set")


_EVENT = {"event_id": "ev1", "event_name": "Workshop", "teams_channel_id": "chan1",
          "teams_team_id": "team1", "host_user_id": "host1"}
_MEMBER = {"teams_user_id": "u1", "email": "u1@x.com", "role": "member"}


# --- list_event_files ----------------------------------------------------------------------

def test_list_files_enriched_with_catalog_summary(monkeypatch):
    _enable_graph(monkeypatch)
    factory, _ = _factory_with(
        _EVENT, members=[_MEMBER],
        documents=[{"filename": "template.docx", "drive_item_id": "f1",
                    "summary": "Sponsor email template", "doc_type": "template"}],
    )
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    graph = _Graph(children=[
        {"id": "f1", "name": "template.docx"},
        {"id": "sub", "name": "archive", "folder": {}},   # subfolder skipped
        {"id": "f2", "name": "notes.txt"},                # not catalogued → name + id only
    ])
    fn = wiring._build_list_event_files_fn(graph_factory=lambda: graph)
    out = fn(user_id="u1", event_id="ev1")
    assert "template.docx" in out and "Sponsor email template" in out and "template" in out
    assert "id: f1" in out and "id: f2" in out
    assert "archive" not in out  # folder skipped
    assert "external_untrusted_content" in out


def test_list_files_non_member_refused(monkeypatch):
    _enable_graph(monkeypatch)
    factory, _ = _factory_with(_EVENT, members=[])  # u1 is neither member nor host
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    graph = _Graph(children=[{"id": "f1", "name": "x.docx"}])
    called = []
    graph.list_children = lambda *a: called.append(1) or []
    fn = wiring._build_list_event_files_fn(graph_factory=lambda: graph)
    out = fn(user_id="u1", event_id="ev1")
    assert "not a member" in out.lower()
    assert called == []  # never hit Graph


def test_list_files_no_focused_event_guides(monkeypatch):
    out = wiring._build_list_event_files_fn(graph_factory=lambda: _Graph())(
        user_id="u1", event_id=None)
    assert "focus on" in out.lower()


def test_list_files_empty_channel(monkeypatch):
    _enable_graph(monkeypatch)
    factory, _ = _factory_with(_EVENT, members=[_MEMBER])
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    fn = wiring._build_list_event_files_fn(graph_factory=lambda: _Graph(children=[]))
    assert "no files" in fn(user_id="u1", event_id="ev1").lower()


# --- read_event_file -----------------------------------------------------------------------

def test_read_text_file_returns_parsed_text(monkeypatch):
    _enable_graph(monkeypatch)
    factory, _ = _factory_with(_EVENT, members=[_MEMBER])
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    monkeypatch.setattr(
        "eventbuddy.ingestion.parsers.parse",
        lambda f, c: ParsedDoc(kind="docx", filename=f, text="Dear {name}, welcome!"))
    graph = _Graph(content=(b"bytes", "template.docx", "application/docx"))
    fn = wiring._build_read_event_file_fn(graph_factory=lambda: graph)
    out = fn(user_id="u1", event_id="ev1", file_id="f1")
    assert "Dear {name}, welcome!" in out
    assert "external_untrusted_content" in out
    assert graph.downloaded == [("drive1", "f1")]


def test_read_image_uses_vision(monkeypatch):
    _enable_graph(monkeypatch)
    monkeypatch.setattr(wiring.settings, "llm_vision_enabled", True)
    factory, _ = _factory_with(_EVENT, members=[_MEMBER])
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    monkeypatch.setattr(
        "eventbuddy.ingestion.parsers.parse",
        lambda f, c: ParsedDoc(kind="image", filename=f, raw_bytes=b"img", mime="image/png"))

    class _Vision:
        def describe_image(self, b, m, instr, *, model=None):
            return "A flyer for the keynote."
    monkeypatch.setattr("eventbuddy.integrations.llm.client.LLMGateway", lambda: _Vision())
    graph = _Graph(content=(b"img", "flyer.png", "image/png"))
    fn = wiring._build_read_event_file_fn(graph_factory=lambda: graph)
    out = fn(user_id="u1", event_id="ev1", file_id="f9")
    assert "A flyer for the keynote." in out


def test_read_image_vision_disabled_degrades(monkeypatch):
    _enable_graph(monkeypatch)
    monkeypatch.setattr(wiring.settings, "llm_vision_enabled", False)
    factory, _ = _factory_with(_EVENT, members=[_MEMBER])
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    monkeypatch.setattr(
        "eventbuddy.ingestion.parsers.parse",
        lambda f, c: ParsedDoc(kind="image", filename=f, raw_bytes=b"img", mime="image/png"))
    fn = wiring._build_read_event_file_fn(graph_factory=lambda: _Graph(
        content=(b"img", "flyer.png", "image/png")))
    out = fn(user_id="u1", event_id="ev1", file_id="f9")
    assert "vision isn't configured" in out.lower()


def test_read_live_each_call(monkeypatch):
    _enable_graph(monkeypatch)
    factory, _ = _factory_with(_EVENT, members=[_MEMBER])
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    monkeypatch.setattr(
        "eventbuddy.ingestion.parsers.parse",
        lambda f, c: ParsedDoc(kind="docx", filename=f, text="content"))
    graph = _Graph(content=(b"x", "a.docx", "x"))
    fn = wiring._build_read_event_file_fn(graph_factory=lambda: graph)
    fn(user_id="u1", event_id="ev1", file_id="f1")
    fn(user_id="u1", event_id="ev1", file_id="f1")
    assert len(graph.downloaded) == 2  # no snapshot cache — re-downloaded


def test_read_no_id_or_link_guides(monkeypatch):
    out = wiring._build_read_event_file_fn(graph_factory=lambda: _Graph())(
        user_id="u1", event_id="ev1")
    assert "list_event_files" in out or "link" in out.lower()


def test_read_non_member_refused(monkeypatch):
    _enable_graph(monkeypatch)
    factory, _ = _factory_with(_EVENT, members=[])  # not a member/host
    monkeypatch.setattr("eventbuddy.data.db.session_scope", factory)
    fn = wiring._build_read_event_file_fn(graph_factory=lambda: _Graph())
    assert "not a member" in fn(user_id="u1", event_id="ev1", file_id="f1").lower()
