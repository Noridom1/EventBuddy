"""Impl 4, Part 0 — the attachment-intake seam: the router extracts file descriptors from the
activity (skipping cards), and the orchestrator threads them onto RequestContext + injects an
awareness note into the human turn so the model knows to read them."""
from types import SimpleNamespace

from eventbuddy.agent.orchestrator import Orchestrator
from eventbuddy.bot.activity_router import _attachments


def _att(content_type=None, content=None, content_url=None, name=None):
    return SimpleNamespace(
        content_type=content_type, content=content, content_url=content_url, name=name
    )


def _activity(attachments):
    return SimpleNamespace(attachments=attachments)


# --- router descriptor extraction ----------------------------------------------------------

def test_extracts_teams_file_download_info():
    act = _activity([
        _att(
            content_type="application/vnd.microsoft.teams.file.download.info",
            content={"downloadUrl": "https://dl", "fileType": "csv"},
            name="roster.csv",
        )
    ])
    assert _attachments(act) == [{
        "name": "roster.csv",
        "content_type": "application/vnd.microsoft.teams.file.download.info",
        "download_url": "https://dl",
        "content_url": None,
    }]


def test_extracts_sharepoint_content_url():
    act = _activity([_att(content_type="reference", content_url="https://sp/file", name="x.xlsx")])
    out = _attachments(act)
    assert out[0]["content_url"] == "https://sp/file" and out[0]["download_url"] is None


def test_skips_adaptive_card_and_html_attachments():
    act = _activity([
        _att(content_type="application/vnd.microsoft.card.adaptive", content={"x": 1}),
        _att(content_type="text/html", content="<p>hi</p>"),
        _att(content_type="ref", content_url="https://sp/f", name="keep.csv"),
    ])
    out = _attachments(act)
    assert len(out) == 1 and out[0]["name"] == "keep.csv"


def test_skips_attachments_without_any_source():
    act = _activity([_att(content_type="x", content={}, name="nope")])
    assert _attachments(act) == []


def test_no_attachments_yields_empty_list():
    assert _attachments(SimpleNamespace(attachments=None)) == []


def test_extracts_sharepoint_link_from_html_body():
    # A file shared *as a link* shows up only as an <a href> inside the HTML body (Impl 9).
    html = ('<div>Đọc file này '
            '<a href="https://contoso.sharepoint.com/sites/x/kichban-demo.docx">'
            'kichban-demo.docx</a></div>')
    act = _activity([_att(content_type="text/html", content=html)])
    out = _attachments(act)
    assert len(out) == 1
    assert out[0]["name"] == "kichban-demo.docx"
    assert out[0]["content_url"] == "https://contoso.sharepoint.com/sites/x/kichban-demo.docx"


def test_ignores_non_share_links_in_html_body():
    act = _activity([_att(content_type="text/html",
                          content='<a href="https://example.com/page">not a file</a>')])
    assert _attachments(act) == []


# --- orchestrator threading + awareness note ----------------------------------------------

class _FakeSession:
    def get_current_event(self, user_id):
        return "ev-1"


class _CaptureRunner:
    def __init__(self):
        self.text = self.ctx = None

    def run(self, text, ctx):
        self.text, self.ctx = text, ctx
        return "ok"


def _orch(runner):
    return Orchestrator(
        session_store=_FakeSession(),
        provision_fn=lambda **kw: None, resolve_event_fn=lambda q, **kw: None,
        remind_fn=lambda **kw: None, report_fn=lambda **kw: "", query_tasks_fn=lambda **kw: "",
        runner=runner, agent_mode="llm",
        role_resolver=lambda **kw: "host",
    )


def test_attachments_reach_context_and_note_is_injected():
    runner = _CaptureRunner()
    atts = [{"name": "roster.csv", "download_url": "https://dl"}]
    _orch(runner).handle(user_id="u1", channel_id=None, text="here you go", attachments=atts)
    assert runner.ctx.attachments == atts
    assert "roster.csv" in runner.text and "read_participant_file" in runner.text
    assert "here you go" in runner.text


def test_no_attachments_leaves_text_unchanged():
    runner = _CaptureRunner()
    _orch(runner).handle(user_id="u1", channel_id=None, text="hello")
    assert runner.text == "hello"
    assert runner.ctx.attachments == []


def test_with_attachment_note_is_pure_helper():
    note = Orchestrator._with_attachment_note("", [{"name": "a.xlsx"}])
    assert "a.xlsx" in note
    assert Orchestrator._with_attachment_note("x", []) == "x"
