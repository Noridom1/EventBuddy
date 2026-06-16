"""Per-event feedback sources (Impl 2 follow-up): the `set_feedback_sources` tool, workbook
auto-discovery (Option 2), and `FormsResponseSync.sync_drive_item`. No DB — fakes only."""
from eventbuddy.agent.context import RequestContext
from eventbuddy.agent.tools import AgentDeps, build_tools
from eventbuddy.capabilities.forms_sync import FormsResponseSync, discover_workbook
from eventbuddy.ingestion.parsers import ParsedDoc


class _FakeSession:
    def __init__(self):
        self.current = {}

    def set_current_event(self, user_id, event_id):
        self.current[user_id] = event_id

    def get_current_event(self, user_id):
        return self.current.get(user_id)


def _deps():
    calls = {}

    def set_feedback_fn(**kw):
        calls["set"] = kw
        return "Saved the responses workbook link for this event."

    deps = AgentDeps(
        session_store=_FakeSession(),
        provision_fn=lambda **kw: None,
        resolve_event_fn=lambda q, **kw: None,
        remind_fn=lambda **kw: None,
        report_fn=lambda **kw: "report",
        query_tasks_fn=lambda **kw: "tasks",
        set_feedback_fn=set_feedback_fn,
    )
    return deps, calls


def _by_name(tools):
    return {t.name: t for t in tools}


def test_tool_registered_with_two_link_args():
    deps, _ = _deps()
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="moderator")))
    assert "set_feedback_sources" in tools
    assert set(tools["set_feedback_sources"].args) == {"form_url", "workbook_url"}


def test_tool_requires_moderator():
    deps, calls = _deps()
    deps.session_store.set_current_event("u1", "ev-3")
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="member")))
    out = tools["set_feedback_sources"].invoke({"workbook_url": "https://x"})
    assert "permission" in out.lower()
    assert "set" not in calls


def test_tool_needs_at_least_one_link():
    deps, calls = _deps()
    deps.session_store.set_current_event("u1", "ev-3")
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="host")))
    out = tools["set_feedback_sources"].invoke({})
    assert "give me" in out.lower()
    assert "set" not in calls


def test_tool_delegates_only_nonempty_links():
    deps, calls = _deps()
    deps.session_store.set_current_event("u1", "ev-9")
    tools = _by_name(build_tools(deps, RequestContext(user_id="u1", role="host")))
    tools["set_feedback_sources"].invoke({"workbook_url": "https://share/wb.xlsx"})
    # empty form_url is passed through as None so it doesn't clobber an existing value
    assert calls["set"] == dict(event_id="ev-9", form_url=None, workbook_url="https://share/wb.xlsx")


# ---- Option 2: workbook auto-discovery ----

class _DiscGraph:
    def __init__(self, children):
        self._children = children

    def get_channel_files_folder(self, team_id, channel_id):
        return ("drv1", "folder1")

    def list_children(self, drive_id, item_id):
        return self._children


def test_discover_matches_responses_workbook():
    graph = _DiscGraph([
        {"id": "skip", "name": "agenda.docx"},
        {"id": "sub", "name": "archive", "folder": {}},
        {"id": "wb", "name": "AI Workshop(1-15) Responses.xlsx"},
    ])
    assert discover_workbook(graph, "team", "chan") == ("drv1", "wb")


def test_discover_returns_none_when_no_match():
    graph = _DiscGraph([{"id": "x", "name": "guests.xlsx"}, {"id": "y", "name": "notes.pdf"}])
    assert discover_workbook(graph, "team", "chan") is None


def test_discover_degrades_on_graph_error():
    class _Boom:
        def get_channel_files_folder(self, *a):
            raise RuntimeError("graph down")

    assert discover_workbook(_Boom(), "team", "chan") is None


# ---- FormsResponseSync.sync_drive_item (the discovery + link share a code path) ----

class _Repo:
    def __init__(self):
        self.added = []

    def respondent_ids(self, event_id):
        return set()

    def add(self, event_id, *, respondent_id, raw_payload, sentiment=None, themes=None):
        self.added.append(respondent_id)


class _Analyzer:
    def analyze(self, comment):
        return "neutral", []


class _ItemGraph:
    def get_drive_item_content(self, drive_id, item_id):
        return (b"", "Responses.xlsx", "application/xlsx")


def test_sync_drive_item_ingests_rows():
    repo = _Repo()
    rows = [{"Email": "a@x.com", "Rating": 4, "Comment": "ok"}]
    syncer = FormsResponseSync(_ItemGraph(), repo, _Analyzer(),
                               parse=lambda f, c: ParsedDoc(kind="xlsx", filename=f, rows=rows))
    n = syncer.sync_drive_item(event_id="ev1", drive_id="drv1", item_id="wb")
    assert n == 1
    assert repo.added == ["a@x.com"]
