"""Per-chat file catalog (Impl 9) — the intelligence plane for group-chat / 1-1 DM files.

This is the analogue of the channel ingestion pipeline (`IngestionPipeline` → `documents`), but
for files shared in a *chat* rather than a Team channel's SharePoint folder. It does three
things, all best-effort (never raises — the caller emits a clean message):

  • **capture(chat_id, attachments)** — the moment a file is shared, record a cheap `reference`
    row (`filename` + `share_url`, no download, no LLM). This is load-bearing: the share link
    rides only the activity that bore the file and is otherwise lost by the next turn, and a
    1-1 DM has no Graph chat to re-derive it from.
  • **sync(chat_id, scope, attachments, graph)** — gather candidate files from the scope-correct
    source(s) (group → Graph message scan + current attachments; personal → attachments only,
    *never* `/chats/{a:…}`), capture references, then lazily download + understand the ones not
    yet summarized (bounded per call). Idempotent by `drive_item_id`.
  • **match(chat_id, query)** — resolve a name/description to a file, returning a confident single
    hit or a candidate set for disambiguation.

No auto-ingestion / no on-join hook — every entry point is driven by the user's own call.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from eventbuddy.common.logging import get_logger

log = get_logger("capabilities.chat_files_catalog")

# How many not-yet-summarized files to download + understand inline on a single sync, so a chat
# with many files doesn't stall one turn behind N LLM/vision calls. The rest summarize on later
# turns; reference rows still list + match by name immediately.
MAX_SUMMARIES_PER_SYNC = 5
# A version suffix ("v2", "version 4", "(2)") — stripped when grouping versioned files so
# "the master plan" collapses its versions into one candidate group.
_VERSION_RE = re.compile(r"[\s_\-]*\(?\bv(?:ersion)?\.?\s*\d+\)?", re.I)
_WORD_RE = re.compile(r"[\w]+")


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def _stem(filename: str) -> str:
    """A filename's match stem: drop the extension and any version suffix."""
    name = _norm(filename)
    name = re.sub(r"\.[a-z0-9]{1,5}$", "", name)  # extension
    return _VERSION_RE.sub("", name).strip()


def _words(s: str) -> list[str]:
    return _WORD_RE.findall(_norm(s))


def score_file(query: str, *, filename: str, summary: str | None = None,
               doc_type: str | None = None) -> int:
    """Rank how well a catalog file matches `query` (higher = better; 0 = no match). The
    filename dominates (exact > stem-exact > prefix > substring > all-query-words-present), with
    a smaller bonus when the query words appear in the summary/doc_type — so a *description*
    ("the participant list") matches `participants.csv` whose summary mentions participants."""
    q = _norm(query)
    if not q:
        return 0
    name = _norm(filename)
    stem = _stem(filename)
    score = 0
    if q == name or q == stem:
        score = 100
    elif name.startswith(q) or stem.startswith(q):
        score = 80
    elif q in name:
        score = 60
    else:
        q_words = [w for w in _words(q) if len(w) > 2]
        if q_words:
            name_words = set(_words(filename))
            if all(w in name_words for w in q_words):
                score = 50
            else:
                hay = set(_words(f"{summary or ''} {doc_type or ''}"))
                hits = sum(1 for w in q_words if w in name_words or w in hay)
                if hits:
                    score = 20 + 10 * hits  # partial description match
    return score


@dataclass
class MatchResult:
    exact: object | None = None          # a single confident hit (ChatFile)
    candidates: list = field(default_factory=list)  # ambiguous hits (ChatFile rows)


def rank_files(query: str, rows: list) -> MatchResult:
    """Pure ranking over catalog rows (objects with `.filename`/`.summary`/`.doc_type`). One
    clear winner → `exact`; several comparable hits → `candidates` (deduped to one per version
    group so v1/v2/v4 of one document surface as that document, ordered newest-first as given)."""
    scored = []
    for r in rows:
        s = score_file(query, filename=getattr(r, "filename", ""),
                       summary=getattr(r, "summary", None),
                       doc_type=getattr(r, "doc_type", None))
        if s > 0:
            scored.append((s, r))
    if not scored:
        return MatchResult()
    scored.sort(key=lambda t: t[0], reverse=True)
    top = scored[0][0]
    contenders = [r for s, r in scored if s >= max(40, top - 15)]
    if not contenders:
        # Only weak (description-only) matches — keep everything tied at the best score, so a
        # lone weak hit still resolves while two equally-weak hits still disambiguate.
        contenders = [r for s, r in scored if s == top]
    # Distinct underlying documents among the contenders (collapse version groups).
    groups: dict[str, list] = {}
    for r in contenders:
        groups.setdefault(_stem(getattr(r, "filename", "")), []).append(r)
    if len(groups) == 1 and len(contenders) == 1:
        return MatchResult(exact=contenders[0])
    if len(groups) == 1:
        # Same document, multiple versions → ask which version.
        return MatchResult(candidates=contenders)
    return MatchResult(candidates=contenders)


class ChatFileCatalog:
    def __init__(self, *, parse=None, understand=None, vision_enabled: bool = False,
                 max_summaries: int = MAX_SUMMARIES_PER_SYNC):
        # Lazy default imports keep this module importable without the ingestion stack present.
        if parse is None:
            from eventbuddy.ingestion.parsers import parse as _parse
            parse = _parse
        if understand is None:
            from eventbuddy.ingestion.understand import understand as _understand
            understand = _understand
        self._parse = parse
        self._understand = understand
        self._vision_enabled = vision_enabled
        self._max_summaries = max_summaries

    # --- public API ------------------------------------------------------------------------

    def capture(self, chat_id: str, attachments: list[dict]) -> int:
        """Record `reference` rows for any share-link attachments on the current turn. Cheap, no
        download/LLM. Best-effort; returns how many rows were touched."""
        if not chat_id or not attachments:
            return 0
        touched = 0
        try:
            from eventbuddy.data.db import session_scope
            from eventbuddy.data.repositories.chat_files import ChatFileRepository
            with session_scope() as s:
                repo = ChatFileRepository(s)
                for a in attachments:
                    url = a.get("content_url")
                    if not url or str(url).startswith("data:"):
                        continue  # only persistent share links are catalogable
                    repo.upsert(chat_id, filename=a.get("name") or "(unnamed)", share_url=url)
                    touched += 1
        except Exception as e:  # noqa: BLE001 — capture is best-effort, never breaks the turn
            log.warning(f"chat-file capture skipped ({type(e).__name__}: {e})")
        return touched

    def sync(self, chat_id: str, *, scope: str, attachments: list[dict] | None = None,
             graph=None) -> list:
        """Discover files (scope-correct), capture references, and lazily summarize the new ones
        (bounded). Returns the chat's catalog rows. Never raises."""
        if not chat_id:
            return []
        attachments = attachments or []
        # 1) gather candidates: attachments (any scope) + group Graph scan.
        candidates: list[dict] = []
        seen: set[str] = set()

        def add(name, url):
            if not url or url in seen or str(url).startswith("data:"):
                return
            seen.add(url)
            candidates.append({"name": name or "(unnamed)", "url": url})

        for a in attachments:
            add(a.get("name"), a.get("content_url"))
        if scope == "group" and graph is not None:
            try:
                for f in graph.list_chat_files(chat_id) or []:
                    add(f.get("name"), f.get("url"))
            except Exception as e:  # noqa: BLE001 — group scan is best-effort
                log.warning(f"chat-file scan failed ({type(e).__name__}: {e})")
        try:
            from eventbuddy.data.db import session_scope
            from eventbuddy.data.repositories.chat_files import ChatFileRepository
            with session_scope() as s:
                repo = ChatFileRepository(s)
                for c in candidates:
                    repo.upsert(chat_id, filename=c["name"], share_url=c["url"])
                # 2) lazily summarize rows that still lack a summary (bounded per sync).
                pending = [r for r in repo.list(chat_id)
                           if not r.summary and r.share_url and r.parse_status != "failed"]
                budget = self._max_summaries
                if pending and graph is None:
                    log.info(f"chat-file sync: {len(pending)} file(s) to summarize but no Graph "
                             "client — leaving as references")
                for r in pending[:budget]:
                    self._summarize_row(repo, r, graph)
                if len(pending) > budget:
                    log.info(f"chat-file sync: summarized {budget}/{len(pending)} pending; "
                             "the rest catalog on later turns")
                return repo.list(chat_id)
        except Exception as e:  # noqa: BLE001
            log.warning(f"chat-file sync failed ({type(e).__name__}: {e})")
            return []

    def _summarize_row(self, repo, row, graph) -> None:
        """Resolve → download → parse → understand one reference row, backfilling the catalog."""
        if graph is None:
            return
        try:
            drive_id, item_id = graph.resolve_share_url(row.share_url)
            content, filename, _mime = graph.get_drive_item_content(drive_id, item_id)
        except Exception as e:  # noqa: BLE001
            log.warning(f"chat-file resolve failed for {row.filename} ({type(e).__name__}: {e})")
            row.parse_status = "failed"
            return
        parsed = self._parse(filename or row.filename, content)
        if parsed.kind == "unsupported":
            repo.upsert(row.chat_id, filename=row.filename, drive_item_id=item_id,
                        doc_type="other", summary="(unsupported file type)",
                        parse_status="failed")
            return
        vision = None
        if self._vision_enabled:
            from eventbuddy.integrations.llm.client import LLMGateway
            vision = LLMGateway()
        from eventbuddy.integrations.llm.client import LLMGateway
        try:
            info = self._understand(parsed, llm=LLMGateway(), vision=vision)
        except Exception as e:  # noqa: BLE001
            log.warning(f"chat-file understand failed for {row.filename} "
                        f"({type(e).__name__}: {e})")
            info = {"summary": "", "doc_type": "other"}
        repo.upsert(row.chat_id, filename=row.filename, drive_item_id=item_id,
                    summary=(info.get("summary") or "").strip() or None,
                    doc_type=info.get("doc_type") or None, parse_status="parsed")

    def match(self, chat_id: str, query: str) -> MatchResult:
        """Resolve a name/description against the chat's catalog. Never raises."""
        try:
            from eventbuddy.data.db import session_scope
            from eventbuddy.data.repositories.chat_files import ChatFileRepository
            with session_scope() as s:
                rows = ChatFileRepository(s).list(chat_id)
                # Detach: read the fields we need into lightweight rows the caller can use
                # outside the session.
                detached = [_Row(r.filename, r.summary, r.doc_type, r.share_url,
                                 r.drive_item_id) for r in rows]
        except Exception as e:  # noqa: BLE001
            log.warning(f"chat-file match failed ({type(e).__name__}: {e})")
            return MatchResult()
        return rank_files(query, detached)


@dataclass
class _Row:
    filename: str
    summary: str | None
    doc_type: str | None
    share_url: str | None
    drive_item_id: str | None
