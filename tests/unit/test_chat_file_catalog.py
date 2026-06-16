"""Impl 9 — per-chat file catalog: matcher, repository idempotency, capture-on-receive, and the
scope-correct lazy sync (group scans Graph; a 1-1 DM uses attachments only, never /chats)."""
import contextlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from eventbuddy.capabilities.chat_files_catalog import (
    ChatFileCatalog,
    rank_files,
    score_file,
)
from eventbuddy.data.repositories.chat_files import ChatFileRepository
from eventbuddy.domain.models import ChatFile
from eventbuddy.ingestion.parsers import ParsedDoc

# --- matcher (pure) ------------------------------------------------------------------------

class _Row:
    def __init__(self, filename, summary=None, doc_type=None, share_url="u", drive_item_id="i"):
        self.filename, self.summary, self.doc_type = filename, summary, doc_type
        self.share_url, self.drive_item_id = share_url, drive_item_id


def test_score_exact_and_prefix_beat_description():
    assert score_file("participants.csv", filename="participants.csv") == 100
    assert score_file("participants", filename="participants.csv") == 100  # stem-exact
    assert score_file("part", filename="participants.csv") == 80           # prefix
    # description-only match (query words land in the summary) scores lower than a name hit
    desc = score_file("registration list", filename="participants.csv",
                      summary="the list of registered attendees")
    assert 0 < desc < 80


def test_rank_single_confident_hit_is_exact():
    rows = [_Row("participants.csv", "attendees"), _Row("budget.xlsx", "costs")]
    result = rank_files("participants", rows)
    assert result.exact is not None and result.exact.filename == "participants.csv"
    assert not result.candidates


def test_rank_versions_of_one_doc_are_ambiguous():
    rows = [
        _Row("Master Plan v1.docx", "plan"),
        _Row("Master Plan v2.docx", "plan"),
        _Row("Master Plan v4.docx", "plan"),
    ]
    result = rank_files("master plan", rows)
    assert result.exact is None
    assert {r.filename for r in result.candidates} == {
        "Master Plan v1.docx", "Master Plan v2.docx", "Master Plan v4.docx"}


def test_rank_no_match_is_empty():
    result = rank_files("nonexistent quarterly report", [_Row("agenda.docx", "agenda")])
    assert result.exact is None and not result.candidates


# --- repository idempotency ----------------------------------------------------------------

def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    ChatFile.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_repo_reference_then_backfill_is_idempotent():
    s = _session()
    repo = ChatFileRepository(s)
    # 1) capture a reference (no item id yet) — dedupe by share_url on a repeat.
    _, created = repo.upsert("chat1", filename="roster.csv", share_url="https://x/roster")
    assert created
    _, created2 = repo.upsert("chat1", filename="roster.csv", share_url="https://x/roster")
    assert not created2
    # 2) backfill the resolved item id + summary — still the same row.
    repo.upsert("chat1", filename="roster.csv", share_url="https://x/roster",
                drive_item_id="item-9", summary="a roster", doc_type="roster",
                parse_status="parsed")
    s.commit()
    rows = repo.list("chat1")
    assert len(rows) == 1
    assert rows[0].drive_item_id == "item-9" and rows[0].summary == "a roster"
    assert repo.known_item_ids("chat1") == {"item-9"}
    # 3) a later sync that re-sees the resolved item dedupes by drive_item_id.
    _, created3 = repo.upsert("chat1", filename="roster.csv", drive_item_id="item-9")
    assert not created3
    assert len(repo.list("chat1")) == 1


# --- catalog sync + capture (sqlite-redirected session_scope) ------------------------------

@pytest.fixture
def patched_db(monkeypatch):
    session = _session()

    @contextlib.contextmanager
    def fake_scope():
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise

    monkeypatch.setattr("eventbuddy.data.db.session_scope", fake_scope)
    return session


class _Graph:
    def __init__(self, chat_files=None):
        self._chat_files = chat_files or []
        self.calls = []

    def list_chat_files(self, chat_id, limit=50):
        self.calls.append(("list", chat_id))
        return self._chat_files

    def resolve_share_url(self, url):
        self.calls.append(("resolve", url))
        return ("drive-1", f"item-for-{url.rsplit('/', 1)[-1]}")

    def get_drive_item_content(self, drive_id, item_id):
        return (b"bytes", f"{item_id}.csv", "text/csv")


def _catalog():
    return ChatFileCatalog(
        parse=lambda f, c: ParsedDoc(kind="csv", filename=f, text="a,b\n1,2"),
        understand=lambda parsed, *, llm, vision: {"summary": "a table", "doc_type": "roster"},
        vision_enabled=False,
    )


def test_capture_records_reference_no_download(patched_db):
    cat = _catalog()
    n = cat.capture("chat1", [
        {"name": "plan.docx", "content_url": "https://x/plan"},
        {"name": "skip.docx", "content_url": "data:..."},   # inline upload — not catalogable
        {"name": "nolink.docx"},                            # no url — skipped
    ])
    assert n == 1
    rows = ChatFileRepository(patched_db).list("chat1")
    assert [r.filename for r in rows] == ["plan.docx"]
    assert rows[0].parse_status == "reference" and rows[0].summary is None


def test_sync_personal_uses_attachments_only_never_graph(patched_db):
    cat = _catalog()
    graph = _Graph(chat_files=[{"name": "should-not-see.docx", "url": "https://x/nope"}])
    rows = cat.sync("a:1Wx7", scope="personal", graph=graph,
                    attachments=[{"name": "shared.csv", "content_url": "https://x/shared"}])
    # personal scope must NOT scan Graph messages, only resolve the attachment we passed.
    assert ("list", "a:1Wx7") not in graph.calls
    names = {r.filename for r in rows}
    assert "shared.csv" in names and "should-not-see.docx" not in names
    shared = next(r for r in rows if r.filename == "shared.csv")
    assert shared.summary == "a table" and shared.parse_status == "parsed"


def test_sync_group_scans_graph_and_is_incremental(patched_db):
    cat = _catalog()
    graph = _Graph(chat_files=[{"name": "agenda.docx", "url": "https://x/agenda"}])
    cat.sync("19:g@thread.v2", scope="group", graph=graph, attachments=[])
    assert ("list", "19:g@thread.v2") in graph.calls
    # Second sync: the file is already cataloged → no re-resolve of the same item.
    graph.calls.clear()
    cat.sync("19:g@thread.v2", scope="group", graph=graph, attachments=[])
    assert ("resolve", "https://x/agenda") not in graph.calls  # idempotent: not re-summarized


def test_match_resolves_by_name_after_sync(patched_db):
    cat = _catalog()
    graph = _Graph()
    cat.sync("a:dm", scope="personal", graph=graph,
             attachments=[{"name": "participants.csv", "content_url": "https://x/participants"}])
    result = cat.match("a:dm", "the participants")
    assert result.exact is not None and result.exact.filename == "participants.csv"
