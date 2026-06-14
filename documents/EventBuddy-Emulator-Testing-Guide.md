# EventBuddy — Manual Testing Guide (Bot Framework Emulator)

A structured plan for exercising EventBuddy by hand. Every test below names **what to set
up**, **what to say/do**, and the **expected behavior** — and is filed under one of two
classes so you know up front what infrastructure each needs.

> **The two classes**
>
> - **Class A — No MS Teams needed (seeded data only).** Runs entirely against the seeded
>   `Demo Workshop` through the Emulator (or the dev HTTP routes). **No Graph creds, no real
>   Teams team, no SharePoint.** The conversation, routing, role gating, HITL **cards**, and
>   the **DB/audit side-effects** are all verifiable here. The *only* thing that degrades is
>   genuine outbound I/O (sending mail, reading files) — it returns a clean "not available"
>   message instead of doing nothing or crashing.
> - **Class B — Needs MS Teams integration.** Requires a **real Teams team + channel**, an
>   app-only **Graph** registration with **admin-consented** permissions, and (for response
>   reads) a real **Forms responses workbook**. These exercise real SharePoint file reads,
>   channel card posts, real Outlook sends, and channel-scoped provisioning. The Emulator
>   alone cannot stand in for any of this.

The Emulator is **not** MS Teams — it is a chat client pointed at `/api/messages`. So a test
being "doable in the Emulator" is exactly Class A. Class B is verified by adding the deployed
bot to an actual Teams channel (or by feeding real Graph identifiers), not through the
Emulator UI.

---

## 0. One-time setup (shared by both classes)

### 0.1 `.env` keys

| Key | Class A | Class B | Notes |
|---|---|---|---|
| `DATABASE_URL` | ✅ required | ✅ required | Seeded data + reports/audit live here. |
| `REDIS_URL` | recommended | recommended | Working-memory window; degrades to in-memory without it. |
| `MAAS_*` (LLM creds) | recommended | recommended | Absent → orchestrator runs the **regex router** (still routes focus / report / tasks / create / remind, but no free-form tool-calling). |
| `DEV_ROUTES_ENABLED` | `true` (for curl) | `true` | Enables `/api/dev/handle` + `/api/dev/confirm`. **Off in production.** |
| `MICROSOFT_APP_ID` / `MICROSOFT_APP_PASSWORD` | match Emulator | match Emulator | What you type in the Emulator's **Open Bot** dialog (or leave all blank). |
| `GRAPH_TENANT_ID` / `GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET` | — (leave unset) | ✅ required | Real send + file/workbook reads. Without them Class A still works; Class B degrades to "not available." |
| `FEEDBACK_FORM_URL` | optional | optional | Global fallback feedback Form link (`{event_id}` interpolated). Prefer per-event. |
| `FEEDBACK_WORKBOOK_URL` | leave empty | optional | Global fallback responses-workbook link. **Leave empty** unless one workbook serves all events — prefer per-event `set_feedback_sources`. |

> **Class B Graph permissions:** app-only `Files.Read.All` + `Sites.Read.All`
> (+ `Team.ReadBasic.All` / `Group.Read.All`), with **tenant admin consent**, plus `Mail.Send`
> for real Outlook sends. A deploy-time/ops step, not code.

### 0.2 Migrate + seed

```bash
venv/bin/alembic upgrade head                 # applies 0004 (per-event feedback columns)
make seed HOST_USER_ID=<your Emulator User ID>
```

Seeds **Demo Workshop**: 3 members (2 registered, 1 pending), 3 tasks, 2 analyzed feedback
rows, and a demo `feedback_form_url`. The `HOST_USER_ID` **must equal** the identity you test
as (Emulator **Settings → User ID**, or the `user_id` you POST to `/api/dev/handle`) — otherwise
"my tasks" and focus won't resolve to you.

### 0.3 Point the Emulator at the bot

1. **Settings →** set the **ngrok** path and enable "Run ngrok when connecting to a remote
   endpoint." A remote/deployed bot replies via a callback to the Emulator's `serviceUrl`, so
   it needs ngrok. (Local `make run` on `localhost:8080` does not.)
2. **Open Bot →** endpoint `https://<endpoint>/api/messages`; enter the deployed
   `MICROSOFT_APP_ID` / `PASSWORD` (or leave blank if the runtime has none).
3. **Settings → User ID =** the `HOST_USER_ID` you seeded.

### 0.4 ngrok-free alternative (scripted)

Clicking an Adaptive Card against a *remote* bot needs ngrok. To test the HITL **confirm** leg
without it, use the dev routes (require `DEV_ROUTES_ENABLED=true`):

```bash
EP=$(make -s endpoint)        # or EP=http://localhost:8080 when running locally
curl -s $EP/api/dev/handle  -H 'content-type: application/json' \
  -d '{"user_id":"dev-user","text":"focus on Demo Workshop"}' | jq
curl -s $EP/api/dev/confirm -H 'content-type: application/json' \
  -d '{"user_id":"dev-user","action":"mail","pending_id":"<from the card>"}' | jq
```

`/api/dev/handle` returns `{reply, cards?}`; `cards` is present only when a HITL flow emitted
one. The `pending_id` for `/api/dev/confirm` comes from that card. Confirm re-auth requires
**clicker == preparer** and role ≥ moderator.

---

## Class A — No MS Teams needed (seeded data only)

All of these run through the Emulator (or the dev routes) against `Demo Workshop`, with **no
Graph creds**. Focus the event first; it stays focused for the rest of the conversation.

### A1 — Focus an event
- **Say:** `focus on Demo Workshop`
- **Expect:** `Focused on 'Demo Workshop'.` Subsequent task/report/reminder actions now target it.
- **Negative:** `focus on Nonexistent Event` → `I couldn't find an event matching 'Nonexistent Event'.`

### A2 — List my tasks
- **Setup:** seeded as the host (`HOST_USER_ID`), who owns "Prepare slides" + "Book the room."
- **Say:** `what are my tasks?`
- **Expect:** the caller's assigned tasks in the focused event, with statuses (todo / in_progress).
- **Negative (no focus):** reset, then ask without focusing → prompt to focus an event first.

### A3 — Update a task status
- **Say:** `mark "Book the room" as done`
- **Expect:** confirmation the task moved to `done`. Re-run **A2** → it reflects `done`.
- **Authorization:** you (host) may update any task; a plain member may update only their own.
  Verify side-effect: `SELECT task_name, status FROM tasks WHERE event_id='<id>';`

### A4 — Set per-event feedback sources
- **Say:** `set the feedback form to https://forms.office.com/r/demo` then
  `set the feedback workbook to https://contoso.sharepoint.com/.../Responses.xlsx`
- **Expect:** a saved-confirmation for each. Setting one must **not** clobber the other.
- **Authorization:** as a member → "You don't have permission … (needs host or moderator)."
- **Side-effect:** `SELECT feedback_form_url, feedback_workbook_url FROM events WHERE event_id='<id>';`
- *(Note: the link is just stored here. Actually **reading** the workbook is Class B / B3.)*

### A5 — Generate the AI report ★ (the headline Class A flow)
- **Setup:** seeded feedback rows already give the report real data; **no workbook fetch
  happens** when no per-event/global workbook link is set, so this works with no Graph.
- **Say:** `generate the report`
- **Expect:**
  1. a **report card** — metrics (response count, avg rating, sentiment split) + an LLM
     summary + next-event suggestions, read-only;
  2. a **confirm card** — "email the report to the manager?" (a `mail` HITL pending action);
  3. reply text pointing at the card.
- **Side-effects:** a new `reports` row; an `audit_log` row `action=report, result=generated`.
  ```sql
  SELECT * FROM reports ORDER BY generated_at DESC LIMIT 1;
  SELECT action, tool_name, result FROM audit_log ORDER BY created_at DESC LIMIT 5;
  ```

### A6 — Confirm the report email (HITL gate, draft-only without Graph)
- **Do:** click **✅ Confirm & send** on A5's confirm card (or `/api/dev/confirm` with
  `action=mail` + the emitted `pending_id`).
- **Expect (no Graph creds):** the confirm path runs, re-auth passes, and the send degrades to
  a clean "sending isn't available" message — **no crash** — with the attempt audited.
- **Re-auth negatives:** a *different* `user_id` confirming → refused (clicker ≠ preparer);
  reusing a spent `pending_id` → refused (one-shot token).

### A7 — Draft an Outlook email (HITL draft)
- **Say:** `email the members that the venue changed to Room 401`
- **Expect:** a confirm card (draft only); confirming behaves like A6 (real send is Class B).
- **Authorization:** member → permission refusal.

### A8 — Prepare reminders (HITL card)
- **Say:** `remind everyone about their tasks`
- **Expect:** a reminder confirm card; confirming sends individually with Graph, or the clean
  no-Graph message here. Member → permission refusal.

### A9 — Create an event (DB-only, no channel)
- **Say:** `create event "QA Test Day" members: a@x.com, b@x.com`
- **Expect:** `Created event 'QA Test Day' (id …)`. Persists locally; **no Teams channel is
  bound** without Graph (channel binding is Class B / B4). Member → permission refusal.
- **Side-effect:** `SELECT event_name FROM events WHERE event_name='QA Test Day';`

### A10 — Feedback jobs, scripted (no scheduler wait, no Graph)
- **Run:**
  ```bash
  venv/bin/python -c "from eventbuddy.scheduler.jobs import run_feedback_send; run_feedback_send('<event_id>')"
  venv/bin/python -c "from eventbuddy.scheduler.jobs import run_feedback_followup; run_feedback_followup('<event_id>')"
  ```
- **Expect (no Graph):** each marks its `scheduled_jobs` row `failed` ("form link / Graph not
  configured") and **never crashes**. `run_feedback_followup` targets only non-responders
  (member emails minus those already in `feedback_responses` — case-insensitive).
- **Side-effect:** `SELECT job_type, status FROM scheduled_jobs;`

### A11 — Graceful degradation & guards (cross-cutting)
- **No LLM creds:** the orchestrator falls back to the **regex router** — `focus`, `generate
  report`, `my tasks`, `create event`, `remind` still route; arbitrary phrasing may not.
- **No event focused:** report / tasks / update / ingest all prompt to focus first.
- **Identity can't be spoofed:** there is no way to pass a different user/role in the
  message — identity comes from the server context. (Confirm by trying; the model has no such
  tool argument.)

---

## Class B — Needs MS Teams integration

Requires a real Teams team/channel, Graph app creds with admin consent, and (for B3) a real
Forms responses workbook. Verify by adding the deployed bot to a channel and/or feeding real
Graph identifiers. The Emulator alone is insufficient.

### B1 — Ingest a SharePoint/OneDrive **link**
- **Setup:** Graph creds; a share link to a real `.xlsx` / `.docx` / `.pdf` roster/agenda.
- **Say (event focused):** `ingest this file <SharePoint share link>`
- **Expect:** the link resolves → file downloads → parses → LLM structures members/tasks →
  `documents` row (idempotent by `drive_item_id`) + new members/tasks; if anyone is
  unregistered, a **proactive invite confirm card** posted to the channel.
- **Side-effects:**
  ```sql
  SELECT filename, parse_status FROM documents;
  SELECT display_name, registration_status FROM event_members WHERE event_id='<id>';
  ```
- **Note:** link ingest works from a URL alone (no `team_id`). Re-ingesting the same item is a
  no-op (idempotent).

### B2 — Ingest the **channel's** SharePoint files
- **Setup:** Graph creds **and** a real Teams `team_id` for the focused event's channel
  (channel pull resolves the channel's backing document library via `filesFolder`).
- **Say:** `ingest the files in this channel`
- **Expect:** scans the channel folder, ingests each supported file, same downstream as B1.
- **Caveat:** the build reuses `microsoft_app_tenant_id` as the Graph `team_id`; a real Teams
  `team_id` is required for live channel operations. Without it this degrades cleanly.

### B3 — Report with a **real Forms responses workbook**
- **Setup:** Graph creds; set the event's workbook link (A4) to a real "Open in Excel" share
  link of the Form's **responses** workbook.
- **Say:** `generate the report`
- **Expect:** before computing metrics, `FormsResponseSync` resolves the share link →
  downloads → parses rows → analyzes sentiment/themes → stores **new** `FeedbackResponse` rows
  (idempotent by row key). The report card then reflects the freshly pulled responses.
- **Resolution order:** per-event `feedback_workbook_url` → global `FEEDBACK_WORKBOOK_URL` →
  channel auto-discovery (scan the channel folder for a `*Responses*.xlsx`).
- **Reminder:** MS Forms has **no supported response API** — the workbook read is the only
  tested path. (`POST /api/webhooks/forms` exists as an unwired Power-Automate fallback.)

### B4 — Create event that **provisions a Teams channel**
- **Setup:** Graph creds + team context.
- **Say:** `create event "Launch Party" members: ...`
- **Expect:** event persists **and** binds a Teams channel (`teams_channel_id` set). Without
  Graph (Class A / A9) it persists locally only.

### B5 — Real Outlook sends (confirm leg of A6–A8)
- **Setup:** Graph creds + `Mail.Send`.
- **Do:** run A5/A7/A8 then confirm the card.
- **Expect:** **individual** Outlook messages per recipient (never a shared To/CC — PII §11),
  an `audit_log` row `result=sent`, and the real email delivered.

### B6 — Real scheduled reminders / feedback dispatch
- **Setup:** Graph creds; a configured Form link (per-event or global).
- **Run:** the B-version of A10 (`run_feedback_send` / `run_feedback_followup`) or wait for the
  APScheduler D-3/D-1/H-1 / post-event jobs.
- **Expect:** Forms link / reminder mailed individually; `scheduled_jobs` → `sent`; `audit_log`
  row. Followup targets non-responders only.

### B7 — Channel card posts & proactive HITL in a real channel
- **Setup:** bot installed in a real Teams channel.
- **Trigger:** B1/B2 ingestion that finds unregistered members.
- **Expect:** the invite confirm card is **posted to the channel** via Graph
  (`send_channel_card`); clicking **Confirm** sends the Outlook invites and audits them.

---

## Quick side-effect cheat-sheet (cloud DB)

```sql
SELECT action, tool_name, result FROM audit_log ORDER BY created_at DESC LIMIT 10;
SELECT * FROM reports ORDER BY generated_at DESC LIMIT 1;
SELECT filename, parse_status FROM documents;
SELECT job_type, status FROM scheduled_jobs;
SELECT event_name, teams_channel_id, feedback_form_url, feedback_workbook_url FROM events;
SELECT display_name, role, registration_status FROM event_members WHERE event_id='<id>';
```

## Coverage map (capability → class)

| Capability | Class A (Emulator + seed) | Class B (Teams/Graph) |
|---|---|---|
| Focus / list tasks / update task | ✅ full | — |
| Set per-event feedback sources | ✅ store link | reading the workbook → B3 |
| Generate report (card + audit) | ✅ from seeded rows | + live workbook fetch (B3) |
| HITL confirm cards (mail/remind/invite) | ✅ card + re-auth + audit | + real send (B5/B7) |
| Create event | ✅ DB-only | + channel provisioning (B4) |
| Prepare reminders / draft mail | ✅ card | + real send (B5) |
| Feedback jobs (scripted) | ✅ degrade-to-failed path | + real dispatch (B6) |
| Ingest files (link / channel) | — | ✅ B1 / B2 |
| Graceful degradation & role guards | ✅ full | — |
