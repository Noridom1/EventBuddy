# Implementation 9 — Group-Chat File Intelligence: Catalog, Describe→Match→Read, Disambiguation Picker (implemented)

Status: **complete** on branch `impl-8-teams-dm-batch-ux` (implemented 2026-06-16). **474 unit tests green** (17 new), `ruff check src/ tests/` clean, **one migration** (`0008` — the `chat_files` table; offline SQL verified). App imports cleanly. Implementation plan: [__plans__/16-impl9-chat-file-catalog-describe-read.md](../__plans__/16-impl9-chat-file-catalog-describe-read.md).

This is the ninth implementation. Impl 8 made group-chat / 1-1 DM files *listable and readable* but dumb — name + URL only, live read, the model had to copy an exact share URL. Impl 9 makes them **intelligent**: a per-chat catalog with stored summaries, so a user can ask for a file by **name or description**, the server resolves it, and when several files fit it asks with a **dropdown picker** — then reads the chosen one(s) and answers. It also fixes the two live failures that motivated it: the `recursion_limit=8` crash when the model hunted for a file, and the `/chats/{a:…}` 404 in a 1-1 DM.

This builds on the **group-chat flat-permissions** change (every group participant resolves to `moderator`), which is what made the roster/read tools reachable in a group chat and exposed the looping bug.

---

## The two live bugs it fixes

1. **`GraphRecursionError` (loop-to-crash).** Asked to read a file, the model called `read_participant_file(link='participants.csv')` (filename in the `link` slot — unresolvable) or `link=''` (empty), got a non-terminal "upload a file" guidance string, re-listed, retried, and exhausted the ReAct step cap → the whole turn errored out.
2. **`/chats/{a:…}` 404 in a 1-1 DM.** A bot DM has **no Microsoft Graph `chat` resource** — `conversation.id` is a Bot Framework id (`a:…`), not a Graph chat id — so `list_event_files` → `/chats/{a:…}/messages` always 404'd, even though the shared file was readable on the caller's behalf. The link was also **transient**: it rode only the activity that bore the file, and the model retained just the filename.

---

## What the agent can do now (new this implementation)

| # | Capability | Surface | New? |
|---|-----------|---------|------|
| 1 | **Read a chat file by name/description** — "read participants.csv", "the agenda", "the master plan"; the server resolves it against the chat catalog (a non-URL `link` is treated as a name) | `read_event_file`, `read_participant_file` | ✅ new |
| 2 | **Real summaries when listing** — `list_event_files` in a group/DM lists stored `{summary, doc_type}` (no more hallucinated-from-filename summaries); a second call adds only new files | `list_event_files` | ✅ changed |
| 3 | **Disambiguation picker** — several files match → a multi-select **dropdown** card (+ "show all files"); the submit re-enters the agent to read the chosen file(s) and answer the original question. Text fallback always works too | `file_pick_card` + `read_files` re-entry | ✅ new |
| 4 | **Read a just-shared file directly** — a file shared this turn is the preferred source in every scope (no Graph chat scan) | `read_event_file` (no args) | ✅ changed |
| 5 | **Files survive across turns** — a file's reference (`name` + `share_url`) is captured the moment it's shared, so naming it on a later turn still resolves | capture-on-receive | ✅ new |
| — | **Graceful loop handling** — a recursion-cap hit returns a clean "tell me the file name" message instead of crashing/degrading; limit bumped 8→12 | `runner.run` | ✅ changed |
| — | **Link captured from every delivery form** — `reference` attachment, **HTML-body hyperlink**, or card | `_attachments` | ✅ changed |

The headline use case works end-to-end: in a 1-1 DM the user shares a SharePoint `.docx` and says *"đọc file này"* → the agent reads the current attachment directly (no 404). In a group chat *"read the participant list and who hasn't registered"* → it resolves `participants.csv` by description, reads it, and answers; if there were `participants v1/v2/v4` it posts the dropdown picker first.

---

## The design: the server owns file resolution; the model only names

```
user: "read the participant list and who hasn't registered"
      │  read_participant_file(link="participant list")     ← a NAME, not a URL (rule 2: scope/chat_id server-built)
      ▼
ChatFileCatalog.sync(chat_id, scope, attachments, graph)    ← lazy, user-driven: scope-correct discovery
      │     group → /chats/{19:…}/messages + attachments      (no auto-ingest, no on-join hook)
      │     personal → attachments ONLY (never /chats/{a:…})
      ▼
match(query, catalog)  ── exact ──► resolve share_url ─► download ─► extract_roster ─► answer
      │
      └─ many ──► dropdown picker (Action.Submit: read_files) ─► re-enter agent ─► answer original question
```

- **Catalog** — a new `chat_files` table (model `ChatFile`, repo `ChatFileRepository`, migration `0008`), keyed on `chat_id` with **no FK to events** (group chats often have none). Idempotent by `(chat_id, drive_item_id)`; reference rows (pre-resolution) dedupe by `share_url`/`filename`. The analogue of `documents`, for chat files instead of channel SharePoint files.
- **`ChatFileCatalog`** ([capabilities/chat_files_catalog.py](../src/eventbuddy/capabilities/chat_files_catalog.py)) — `capture` (cheap reference upsert on receive, no LLM/download), `sync` (scope-correct discovery + bounded lazy summarize of new files via the existing `understand` step), `match`/`rank_files`/`score_file` (name dominates; description gives a smaller bonus; versions of one document collapse into one candidate group).
- **No auto-ingestion / no on-join hook.** Summarization is lazy on the user's own list/read call. But the file *reference* is captured the moment it's shared (in `orchestrator.handle`), because the link is otherwise lost by the next turn and a DM has no Graph chat to re-derive it.

---

## Cross-cutting rules preserved

- **Rule 2 (server-side authority).** `scope`/`channel_id`/role come from `RequestContext`; `name`/`description`/selected ids are data. The picker card carries only an opaque `pending_id` + chosen names — the candidate set and original question live server-side in the pending store.
- **Read-only.** Catalog sync and reads never mutate the chat or files; no `*.ReadWrite` scopes (reuses Impl 8's `Chat.Read`/`Files.Read.All`).
- **Untrusted content.** Catalog summaries, lists, and file contents stay `<external_untrusted_content>`-wrapped; summaries are LLM-generated → still untrusted.
- **Degradation.** Not signed in / missing scope / empty chat / no match / DB down → clean message, never raises. A current-turn attachment read needs no DB at all. **Personal scope never calls `/chats/{a:…}`.**
- **Flat group permissions.** The read/picker path stays open to all group participants; outbound sends still pass the HITL confirm card.
- **Channel path unchanged.** Channel ingestion (`documents`, event-scoped) and the channel `read_event_file`/`list_event_files` branches behave as in Impl 5 (regression-guarded).

---

## Files

| File | Change |
|---|---|
| [domain/models.py](../src/eventbuddy/domain/models.py) | new `ChatFile` model / `chat_files` table |
| [data/repositories/chat_files.py](../src/eventbuddy/data/repositories/chat_files.py) | **new** `ChatFileRepository` (idempotent upsert, `known_item_ids`) |
| [alembic/versions/0008_chat_files.py](../alembic/versions/0008_chat_files.py) | **new** migration |
| [capabilities/chat_files_catalog.py](../src/eventbuddy/capabilities/chat_files_catalog.py) | **new** `ChatFileCatalog` + matcher |
| [agent/wiring.py](../src/eventbuddy/agent/wiring.py) | catalog wired into list/read; `_resolve_named_chat_file`, `_chat_file_disambiguation`, `_read_share_url`, `read_files_resolve`; personal scope no `/chats`; `read_participant_file` gets scope/channel_id |
| [agent/tools.py](../src/eventbuddy/agent/tools.py) | `read_participant_file` passes scope/channel_id; `list_event_files` passes attachments; docstrings (name/describe) |
| [agent/orchestrator.py](../src/eventbuddy/agent/orchestrator.py) | `capture_files_fn` + `_maybe_capture_files` (capture-on-receive, group/DM only) |
| [agent/runner.py](../src/eventbuddy/agent/runner.py) | catch `GraphRecursionError` → terminal message; `RECURSION_LIMIT` 8→12 |
| [bot/activity_router.py](../src/eventbuddy/bot/activity_router.py) | `_attachments` mines HTML-body/card share links; route `read_files` submit → synthesized re-entry turn |
| [bot/cards/builders.py](../src/eventbuddy/bot/cards/builders.py) | **new** `file_pick_card` (multi-select dropdown + "show all") |
| [agent/prompts/system.py](../src/eventbuddy/agent/prompts/system.py) | read-a-file-by-name guidance |
| [documents/EventBuddy-System-Architecture.md](../documents/EventBuddy-System-Architecture.md) | `chat_files` catalog documented |

---

## Tests (17 new)

- **Matcher** — exact/prefix beat description; lone confident hit → exact; versions of one doc → ambiguous; no match → empty.
- **Repository** — reference-then-backfill idempotency (dedupe by url, then by resolved item id).
- **Catalog** — capture records references without download; **personal sync uses attachments only, never Graph**; group sync scans Graph and is incremental; match resolves by name after sync.
- **Wiring** — `list_event_files` lists catalog summaries (group syncs with Graph, DM with `graph=None`); `read_event_file` prefers the current attachment (never consults the catalog); resolves by name → bytes; ambiguous → asks **and emits the picker card** with a server-side pending payload.
- **Router** — `_attachments` extracts a SharePoint link from an HTML body anchor; ignores non-share links.
- **Runner** — a looping model hits the cap and gets a clean message, not `GraphRecursionError`.
- **Orchestrator** — capture-on-receive fires in group/DM with attachments; skipped in a channel and when there are no attachments.

---

## Known limits / follow-ups

- **DM file history is attachment-bounded** — a 1-1 DM has no Graph chat to scan, so only files the bot has *received* (captured) are resolvable; a file never sent to the bot in the DM is unreachable (the agent says so, doesn't 404).
- **Group discovery is a bounded message scan** (inherited from Impl 8); catalog persistence reduces this over time (once seen, always known).
- **Sync summarizes ≤ `MAX_SUMMARIES_PER_SYNC` (5) new files per turn**; the rest list by name immediately and summarize on later turns (logged, no silent cap).
- **"Show all files" in the picker** routes back through the agent's own `list_event_files` rather than re-rendering the full catalog inline — simpler, and reuses the listing path.
