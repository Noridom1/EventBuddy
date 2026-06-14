# Implementation 4 — Participant-Roster Intake → Confirmed Reminders (implemented)

Status: **complete** on branch `impl-3-web-brainstorm-and-teams-email` (implemented 2026-06-14). **314 unit tests green** (59 new), `ruff check src/ tests/` clean, **no migration** (Impl 4 is stateless). App imports cleanly. Implementation plan: [__plans__/11-impl4-roster-file-reminders.md](../__plans__/11-impl4-roster-file-reminders.md).

This is the fourth implementation. Impl 1 built the **action plane** (confirmed sends + audit), Impl 2 the **intelligence plane** (file ingestion + report), Impl 3 widened **reach** (web + channel brainstorm). Impl 4 closes a concrete organizer pain point: *"here's a spreadsheet of the people we invited — chase the ones who haven't registered."*

---

## What the agent can do now (new this implementation)

| # | Capability | Tool / surface | Gate | New? |
|---|-----------|----------------|------|------|
| 1 | **Read a participant roster file** the organizer uploads in chat (or pastes a link to) — .xlsx / .csv / .tsv, any layout — and summarize it (columns, address count, any status column) | `read_participant_file` | moderator+ | ✅ new |
| 2 | **Send a reminder/invitation** to the participants in that file, choosing **Teams or Outlook** on a confirm card; Outlook emails each address individually | `send_participant_reminders` | moderator+ | ✅ new |
| — | **Attachment intake** (enabling) — files attached to a Teams turn now reach the agent | router → graph → orchestrator → ctx | server | ✅ new |

The two delivery modes the organizer asked for both work: a **direct Teams upload** (a pre-authenticated `downloadUrl`, no Graph needed) and a **SharePoint/OneDrive share link** (resolved via Graph, reusing the Impl 2 download path).

---

## The headline distinction: members ≠ participants

This round nails down a domain conflation that existed in the schema (see [__plans__/11](../__plans__/11-impl4-roster-file-reminders.md)):

- **EventMember = organizer** — a Teams user on the organizing team, has a `role` (host/moderator/member), talks to the bot.
- **Participant = attendee** — usually just an email, never talks to the bot, has no role. The roster file is **participants**.

Impl 4 keeps them strictly separate in *concept and behavior*: roster emails are **standalone**, **never persisted**, **never stored as EventMembers**, and **never granted a role**. The `create_event` tool's docstring (which wrongly called its emails "participants") was corrected to say organizing-team members, and the system prompt now teaches the distinction. **Un-splitting the legacy `EventMember.registration_status` field is deliberately deferred** — it needs a migration + reporting changes and would balloon scope; it's documented as a known wart, not touched.

---

## The flow

```
Organizer uploads roster.xlsx (or pastes a SharePoint link) + "remind whoever hasn't registered"
  → router extracts a file descriptor {name, content_type, download_url, content_url}
  → orchestrator puts it on RequestContext.attachments + injects an awareness note into the turn
  → read_participant_file:
        pick the spreadsheet/CSV attachment (else the link)
        download (httpx for a Teams downloadUrl; Graph for a share link)
        parse (xlsx/csv/tsv) → extract_roster (regex-scan every cell for emails, dedupe,
                                                detect the file's own name/status column)
        stash the reading in the transient RosterStore (Redis, TTL) under an opaque token
        return a bounded, untrusted-wrapped summary (counts + ≤3 sample rows + the token)
  → the model DESCRIBES the file and CONFIRMS who to contact with the organizer
  → send_participant_reminders(subject, body, file_token, only_status="no"):
        resolve recipients server-side from the token (only_status filters by the file's status)
        stash a pending mail action + emit the Teams-vs-Outlook channel-choice card
  → organizer clicks a channel on the card → ConfirmHandler re-authorizes (clicker == requester,
        still moderator+) → _perform_send:
            Outlook → graph.send_mail per address (one per recipient, PII §11)
            Teams   → one channel-broadcast notice to the event channel
no Graph creds / no Redis / unsupported file / zero emails / expired token → clean message, never raises
```

Two confirmation gates protect the organizer: the **conversational confirm** (the agent describes the file and asks who to contact) and the **HITL card** (shows the resolved recipient list + body before anything sends — the safety net against a wrong file or filter).

---

## What changed (files)

| Piece | What it does | File |
|---|---|---|
| Attachment descriptor on context | `RequestContext.attachments` (no bytes; rule 2) | [agent/context.py](../src/eventbuddy/agent/context.py) |
| Router intake | `_attachments(activity)` — extract file descriptors, skip card/HTML attachments | [bot/activity_router.py](../src/eventbuddy/bot/activity_router.py) |
| Graph state | `AgentState.attachments`; `run_node` forwards it | [agent/graph.py](../src/eventbuddy/agent/graph.py) |
| Orchestrator | thread `attachments` → ctx; `_with_attachment_note` injects an awareness note into the turn | [agent/orchestrator.py](../src/eventbuddy/agent/orchestrator.py) |
| Dev route | optional `attachments` for exercising intake over HTTP | [api/dev.py](../src/eventbuddy/api/dev.py) |
| CSV/TSV parser | `_parse_csv` (BOM/encoding/delimiter handling); `.csv`/`.tsv` dispatch | [ingestion/parsers.py](../src/eventbuddy/ingestion/parsers.py) |
| Roster extraction | `RosterReading` + `extract_roster` (email regex over all cells; name/status detection) | [ingestion/roster.py](../src/eventbuddy/ingestion/roster.py) *(new)* |
| Download helper | `fetch_attachment_bytes` (downloadUrl via httpx; share link via Graph; size-capped) | [capabilities/attachments.py](../src/eventbuddy/capabilities/attachments.py) *(new)* |
| Transient stash | `RosterStore` (Redis, TTL, repeatable `get` — not the DB) | [agent/roster_store.py](../src/eventbuddy/agent/roster_store.py) *(new)* |
| Capability closures + helpers | `read_participant_file_fn`, `send_participant_reminders_fn`; `_filter_emails_by_status`, `_summarize_roster`, `_pick_roster_attachment`; `mail`+Teams branch in `_perform_send` | [agent/wiring.py](../src/eventbuddy/agent/wiring.py) |
| Tools | `read_participant_file`, `send_participant_reminders` (moderator+, untrusted wrap); `create_event` docstring fix | [agent/tools.py](../src/eventbuddy/agent/tools.py) |
| Card | `reminder_channel_card` shows recipients + body (display-only) | [bot/cards/builders.py](../src/eventbuddy/bot/cards/builders.py) |
| System prompt | member-vs-participant language; read→confirm→send guidance; untrusted-file rule | [agent/prompts/system.py](../src/eventbuddy/agent/prompts/system.py) |

**No migration** — the roster lives only in the transient `RosterStore` and expires; nothing is written to Postgres.

---

## Design decisions honored (user-confirmed 2026-06-14)

- **Read → describe → confirm** — the agent never sends blind; it summarizes the file and confirms recipients first.
- **Both delivery modes** — direct Teams upload (no Graph) and share link (Graph).
- **Standalone participants** — recipients come from the file; not members, not persisted, no roles.
- **Stateless** — no `EventParticipant` table; transient Redis stash only.
- **`create_event` = organizers** — docstring + prompt corrected.
- **Registration marking out of scope** — the file's status column is advisory (drives `only_status` filtering), never written back as EventBuddy state.
- **Teams + Outlook choice** — Outlook emails individually (PII §11); Teams posts one channel notice.

---

## Cross-cutting rules preserved

- **Degradation** — no Graph creds → link download + Outlook send degrade with a clean message (a Teams `downloadUrl` upload still reads); no Redis → the closures catch and degrade; unsupported file / zero emails / expired token / non-moderator → clean message, never a raise.
- **Rule 2 (identity server-side)** — both tools take identity/role/event from `RequestContext`; `read_participant_file` reads `ctx.attachments` (the model can't fabricate a file). Card `Action.Submit` data carries only `{action, pending_id, channel}`.
- **PII §11** — the Outlook branch sends one email per recipient; the roster is stashed server-side and only shown on the confirm card.
- **Untrusted content** — the roster summary is wrapped in the `<external_untrusted_content>` envelope; the prompt forbids treating file contents as instructions.
- **Window discipline** — the read tool returns counts + ≤3 sample rows + a token, never the full address list, so the 4096-token window never has to cut a giant tool result and hundreds of addresses never enter the model's context.

---

## Tests (59 new unit)

- [test_parsers.py](../tests/unit/test_parsers.py) — CSV/TSV parsing (BOM, delimiter sniff, blank rows).
- [test_roster.py](../tests/unit/test_roster.py) — `extract_roster`: emails from any column, dedupe/lowercase, status detection (header + value-based), "Registrant Name" not mistaken for status, empty-when-no-emails.
- [test_attachment_download.py](../tests/unit/test_attachment_download.py) — `fetch_attachment_bytes`: downloadUrl (no Graph), share link (Graph), degrade on error / no-creds, size cap.
- [test_roster_store.py](../tests/unit/test_roster_store.py) — put/get round-trip, repeatable get, TTL.
- [test_participant_tools.py](../tests/unit/test_participant_tools.py) — registration, identity-free schema, moderator gate, delegation (read forwards `ctx.attachments`).
- [test_participant_send.py](../tests/unit/test_participant_send.py) — `_filter_emails_by_status`, `_summarize_roster`, `_pick_roster_attachment`.
- [test_perform_send.py](../tests/unit/test_perform_send.py) — `mail`+Teams posts one channel notice (no email); `mail`+Outlook still per-recipient.
- [test_attachment_intake.py](../tests/unit/test_attachment_intake.py) — router descriptor extraction (skips cards/HTML), orchestrator threading + awareness-note injection.
- Updated [test_graph_wrapper.py](../tests/unit/test_graph_wrapper.py) — `attachments` forwarded through the graph node.

---

## Deploying & testing

### `.env` (no new required keys)
Reuses the existing Graph keys. Direct uploads work with **no** Graph scope (the Teams `downloadUrl` is pre-authenticated). Share-link reading needs Graph `Files.Read.All` / `Sites.Read.All`; sending needs `Mail.Send` (already used by `send_outlook_mail`). `PENDING_ACTION_TTL` doubles as the roster-stash TTL.

### ngrok-free walk (`DEV_ROUTES_ENABLED=true`)
The dev route accepts `attachments`, so the flow is exercisable over HTTP:
```bash
EP=$(make -s endpoint)
curl -s $EP/api/dev/handle -H 'content-type: application/json' -d '{
  "user_id":"dev-user",
  "text":"remind whoever has not registered to sign up",
  "attachments":[{"name":"roster.csv","download_url":"https://.../roster.csv"}]
}' | jq -r '.reply'
# → the agent describes the file + asks who to contact; a follow-up turn confirms, then it
#   emits the Teams-vs-Outlook card. Confirm via /api/dev/confirm with the card's pending_id.
```

---

## Notes / deferred
- **`EventParticipant` table + un-splitting `EventMember.registration_status`** — deferred (needs a migration + reporting repoint). Documented as a known conflation in [__plans__/11](../__plans__/11-impl4-roster-file-reminders.md).
- **Marking participants "registered"** (Forms-response sync, manual) — out of scope; the file's status column is read-only/advisory.
- **Scheduled deadline reminders** — this round is EO-initiated; an APScheduler cron could drive it later.
- **Legacy `.xls`, multi-sheet workbooks beyond the active sheet, Google Sheets links** — not handled; `.xlsx`/`.csv`/`.tsv` cover the ask.
- **Large rosters** — `fetch_attachment_bytes` caps the download at 10 MB; the per-recipient Outlook loop is synchronous (fine for tens/low-hundreds).
