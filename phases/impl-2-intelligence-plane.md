# Implementation 2 — Intelligence Plane (implemented)

Status: **complete** on branch `impl-1-hitl-action-plane` (implemented 2026-06-13, per-event feedback sources added 2026-06-14). **221 unit tests green, 14 integration tests green** against live Postgres, `ruff check` clean, `alembic upgrade head` applies. App imports + `build_orchestrator()` build cleanly. (The two earlier `test_llm_agent_smoke` failures were fixed — see "Fixes" at the end.)

This is the second of the two-implementation split. Where Implementation 1 built the **action plane** (confirmed sends + audit + scheduler), this builds the **intelligence plane**: turning **documents into structured event data** and **feedback into an AI report**. Implementation plan: [__plans__/09-impl2-intelligence-plane.md](../__plans__/09-impl2-intelligence-plane.md). Architecture references: §5.5 (ingestion), §7.2 (document→proactive HITL), §7.5 (feedback→report), §12 (scheduling).

---

## What the agent can do now (new this implementation)

On top of the Impl 1 action plane, EventBuddy now produces intelligence and reads the event's documents/feedback:

| # | Capability | Tool / surface | Gate | New here? |
|---|-----------|----------------|------|-----------|
| 1 | **Generate the AI report** — metrics + LLM summary + next-event suggestions; posts a read-only report card and drafts a manager-summary email behind the HITL gate | `generate_report` + report card + HITL mail card | moderator | **✅ now real** |
| 2 | **Ingest channel SharePoint files / a pasted link** — parse (xlsx/docx/pdf) → LLM-structure → upsert members & tasks → propose inviting non-registered members | `ingest_event_files` + proactive HITL card | moderator | **✅ new** |
| 3 | **Fetch MS Forms feedback** from the responses Excel workbook (the supported path — no Forms response API), analyze sentiment/themes, feed the report | `FormsResponseSync` (pulled by `generate_report`) | system | **✅ new** |
| 4 | **Post-event feedback dispatch** — `feedback_send` (Forms link to all members) and `feedback_followup` (+24h nudge to non-responders only) | APScheduler jobs | pre-authorized by schedule | **✅ now real** |
| 5 | **Set per-event feedback sources** — store this event's Form link + responses-workbook link (each event has its own SharePoint site) | `set_feedback_sources` | moderator | **✅ new** |
| — | Feedback intake push endpoint (Power Automate fallback) | `POST /api/webhooks/forms` | system | thin/unwired |

Cross-cutting, also new:
- **Document ingestion pipeline** (`ingestion/`) — download → parse → structure → upsert, idempotent by `drive_item_id`, posting a proactive bulk-invite confirm card to the channel via Graph.
- **Channel SharePoint access** — resolve a channel's backing document library (`filesFolder`), list + pull files, and resolve sharing links (`/shares/{url}/driveItem`).
- **Reuse of the Impl 1 HITL gate** — the report's manager email and ingestion's bulk invite are both `mail`-type pending actions confirmed through the existing `ConfirmHandler` + `_perform_send`. No new confirm code.

> **MS Forms caveat (load-bearing).** Microsoft Forms has **no supported Graph API to read responses** (`formapi.office.com` is internal/unstable). We read the Form's **responses Excel workbook** (`FEEDBACK_WORKBOOK_URL`, set once by the organizer via "Open in Excel" → share link). Power Automate → `/api/webhooks/forms` is left as an unwired fallback.

---

## The flows

**Report (§7.5).**
```
"generate the report"  →  report_fn:
  • (if FEEDBACK_WORKBOOK_URL set) FormsResponseSync: resolve share link → download → parse rows
        → analyze sentiment/themes → store new FeedbackResponse rows (idempotent)
  • ReportingService: compute_metrics (pure) + LLM summary + LLM next-event suggestions → persist Report
  • emit_card(report_card)                      ← read-only metrics/summary/suggestions
  • emit_card(confirm_card "email the manager?") ← HITL mail pending action
  • audit_log: action=report, result=generated
click [✅ Confirm & send] → ConfirmHandler → _perform_send (individual mail, PII §11) → audit
```

**Ingestion (§7.2).**
```
file in channel / pasted link  →  ChannelFilesService → IngestionPipeline.ingest:
  • graph.get_drive_item_content → parsers.parse (xlsx/docx/pdf, guarded)
  • Extractor.structure (LLM, JSON-only) → {members, tasks}
  • upsert Document (idempotent by drive_item_id) + new members + new tasks (source_document)
  • pending members? → mail pending action + confirm_card posted to the channel via Graph
click [✅ Confirm & send] → ConfirmHandler → individual Outlook invites → audit
```

**Feedback jobs (§7.5).** `run_feedback_send` mails the Forms link to all members; `run_feedback_followup` mails only non-responders (member emails − `feedback_responses` emails). Both: individual sends, `scheduled_jobs` status, `audit_log`, degrade to `failed` without a form link / Graph creds, never crash the scheduler.

---

## Per-event feedback sources (each event → its own SharePoint)

A single global `FEEDBACK_WORKBOOK_URL` / `FEEDBACK_FORM_URL` can't work across many events — every event has its own channel, its own SharePoint site, and its own Form + responses workbook. So both links live **per-event** on the `Event` row (`feedback_form_url`, `feedback_workbook_url`; Alembic `0004`), with the global settings kept only as a fallback.

**Resolution order** (in `report_fn` and the feedback jobs):
1. the event's own `feedback_workbook_url` / `feedback_form_url` (Option 1 — the reliable path);
2. else the global `FEEDBACK_WORKBOOK_URL` / `FEEDBACK_FORM_URL` setting (single-event/demo fallback);
3. else (workbook only) **auto-discovery** — scan the event channel's SharePoint folder for an `.xlsx` whose name looks like a Forms responses workbook (`discover_workbook`, Option 2). Best-effort: Forms often stores response workbooks outside the channel folder, so a per-event link is preferred.

**How the organizer sets it** — conversationally, reusing the link-resolution built for ingestion:
> "set the feedback workbook to https://…/Responses.xlsx"
> "set the feedback form to https://forms.office.com/r/…"

→ the `set_feedback_sources` tool (moderator) stores the link(s) on the focused event (only the provided field is updated, so one doesn't clobber the other). `scripts/seed.py` also seeds a demo `feedback_form_url`.

## What changed (files)

| Piece | What it does | File |
|---|---|---|
| Feedback repo | intake + `respondent_ids`/`respondent_emails` (dedup + non-responder logic) | [data/repositories/feedback.py](../src/eventbuddy/data/repositories/feedback.py) *(new)* |
| Report repo | `create`/`latest` | [data/repositories/reports.py](../src/eventbuddy/data/repositories/reports.py) *(new)* |
| Report math + prose | `compute_metrics` (pure), `generate_summary`, `generate_suggestions` | [domain/reports.py](../src/eventbuddy/domain/reports.py) *(new)* |
| Feedback analyzer | sentiment + theme tags (LLM, JSON fallback) | [domain/feedback.py](../src/eventbuddy/domain/feedback.py) *(new)* |
| Reporting service | compose metrics + summary + suggestions → persist | [capabilities/reporting.py](../src/eventbuddy/capabilities/reporting.py) *(new)* |
| Forms workbook sync | resolve share link → parse rows → analyze → store (idempotent) | [capabilities/forms_sync.py](../src/eventbuddy/capabilities/forms_sync.py) *(new)* |
| Report card | read-only metrics/summary/suggestions card | [bot/cards/report_card.py](../src/eventbuddy/bot/cards/report_card.py) *(new)* |
| Forms intake | thin push fallback endpoint | [api/forms.py](../src/eventbuddy/api/forms.py) *(new)* |
| Parsers | xlsx/docx/pdf → `ParsedDoc` (guarded imports) | [ingestion/parsers.py](../src/eventbuddy/ingestion/parsers.py) *(new)* |
| Extractor | LLM JSON structuring → members/tasks | [ingestion/extractor.py](../src/eventbuddy/ingestion/extractor.py) *(new)* |
| Pipeline | download→parse→structure→upsert→propose invite | [ingestion/pipeline.py](../src/eventbuddy/ingestion/pipeline.py) *(new)* |
| Webhook handler | Graph notification dedup (Redis) + ack | [ingestion/webhook.py](../src/eventbuddy/ingestion/webhook.py) *(new)* |
| Documents repo | `upsert`/`get_by_drive_item` (idempotent) | [data/repositories/documents.py](../src/eventbuddy/data/repositories/documents.py) *(new)* |
| Channel files | pull SharePoint folder / resolve a link → pipeline | [capabilities/channel_files.py](../src/eventbuddy/capabilities/channel_files.py) *(new)* |
| Graph methods | `get_drive_item_content`, `get_channel_files_folder`, `list_children`, `resolve_share_url`, `send_channel_card` | [integrations/graph/client.py](../src/eventbuddy/integrations/graph/client.py) |
| Scheduler jobs | real `run_feedback_send` / `run_feedback_followup` (+ helpers) | [scheduler/jobs.py](../src/eventbuddy/scheduler/jobs.py) |
| Composition root | real `report_fn` (per-event workbook → global → discovery) + `ingest_fn` + `set_feedback_fn` | [agent/wiring.py](../src/eventbuddy/agent/wiring.py) |
| Tools | `generate_report` passes `user_id`; new `ingest_event_files`, `set_feedback_sources` | [agent/tools.py](../src/eventbuddy/agent/tools.py) |
| Event model + repo | `feedback_form_url`/`feedback_workbook_url` columns + `set_feedback_sources` + `create` flush | [domain/models.py](../src/eventbuddy/domain/models.py), [data/repositories/events.py](../src/eventbuddy/data/repositories/events.py) |
| Migration | `0004` — add the two nullable `events` feedback-source columns | [alembic/versions/0004_event_feedback_sources.py](../alembic/versions/0004_event_feedback_sources.py) *(new)* |
| Orchestrator | regex `GENERATE_REPORT` passes `user_id` | [agent/orchestrator.py](../src/eventbuddy/agent/orchestrator.py) |
| Webhook route | real notification handling (dedup → ack), keep token echo | [api/webhooks.py](../src/eventbuddy/api/webhooks.py) |
| Config | `feedback_form_url`, `feedback_workbook_url` | [config.py](../src/eventbuddy/config.py) |
| Main | mount `forms.router` | [main.py](../src/eventbuddy/main.py) |
| Deps | `openpyxl`, `python-docx`, `pypdf` | [pyproject.toml](../pyproject.toml) |
| Seed | + registration statuses + 2 feedback rows (report demo) | [scripts/seed.py](../scripts/seed.py) |

**One migration (`0004`)** — adds the two nullable per-event feedback-source columns to `events`. The report/feedback/ingestion tables (`documents`, `feedback_responses`, `reports`, `scheduled_jobs`) already existed. (RAG/pgvector remains the deferred sub-phase 2.4 and is **not** built.)

---

## Deploying & testing with the Bot Framework Emulator

End-to-end checklist for deploying this build and exercising it from the Emulator.

### 1. `.env` settings (what to add for this implementation)
| Key | Needed for | Notes |
|---|---|---|
| `GRAPH_TENANT_ID` / `GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET` | any real send / file read | Without them the report card + audit still work; sends/ingestion degrade to a clean message. |
| `FEEDBACK_FORM_URL` | feedback dispatch jobs (global fallback) | Templated; `{event_id}` interpolated. Optional if you set links per-event. |
| `FEEDBACK_WORKBOOK_URL` | report Forms-fetch (global fallback) | **Leave empty** unless you run one workbook for all events — prefer per-event (below). A stray non-empty value (e.g. `.`) makes every report attempt a Graph resolve. |
| `DEV_ROUTES_ENABLED=true` | `make smoke` + `/api/dev/*` curl testing | Keep **off** for production (bypasses Bot Framework auth). |
| `MICROSOFT_APP_ID` / `MICROSOFT_APP_PASSWORD` | Emulator auth to `/api/messages` | Match what you enter in the Emulator's Open Bot dialog (or leave all blank). |

> **Graph app permissions** for files/workbook reads: app-only `Files.Read.All` + `Sites.Read.All` (+ `Team.ReadBasic.All`/`Group.Read.All`), with **tenant admin consent**. A deploy-time/ops step, not code.

### 2. Migrate the DB
The container entrypoint runs `alembic upgrade head` on boot (best-effort), so deploying is enough. To migrate by hand (e.g. before seeding from your laptop): `venv/bin/alembic upgrade head` — this applies `0004` (the per-event feedback columns).

### 3. Deploy
```bash
make deploy ENV_FILE=.env          # build → push → create/update runtime → health-check
make endpoint                      # the public HTTPS URL
make health
```

### 4. Seed demo data (into the same cloud DB the runtime reads)
```bash
make seed HOST_USER_ID=<your Emulator User ID>
```
Seeds **Demo Workshop** + 3 members (2 registered, 1 pending) + 3 tasks + 2 analyzed feedback rows + a demo `feedback_form_url`, so "generate the report" has data immediately.

### 5. Point the Emulator at the deployed bot
1. Emulator → **Settings** → set the **ngrok** path and enable "Run ngrok when connecting to a remote endpoint" (the bot replies via a callback to your Emulator's `serviceUrl`, so a remote bot needs ngrok).
2. **Open Bot** → endpoint = `https://<agentbase-endpoint>/api/messages`; enter the deployed `MICROSOFT_APP_ID`/`PASSWORD` (or leave blank if the runtime has none).
3. Emulator → **Settings** → **User ID** = the `HOST_USER_ID` you seeded (so focus / "my tasks" resolve to you).

### 6. Walk the Impl 2 flows in the Emulator
| Say | Expect |
|---|---|
| `focus on Demo Workshop` | "Focused on 'Demo Workshop'." |
| `set the feedback workbook to <SharePoint link to Responses.xlsx>` | "Saved the responses workbook link for this event." (per-event source) |
| `generate the report` | a **report card** (metrics + summary + suggestions) + a **"email the report to the manager?"** confirm card; clicking it sends individually (or the clean no-Graph message) + an `audit_log` row |
| `ingest the files in this channel` *(or paste a SharePoint link)* | `documents` rows + extracted members/tasks; if anyone's unregistered, a proactive **invite** confirm card in the channel |

### 7. ngrok-free alternative (scripted)
The synchronous dev routes need no ngrok/Bot-Framework auth (requires `DEV_ROUTES_ENABLED=true`):
```bash
make smoke                          # Impl 1 HITL loop end-to-end
# or drive Impl 2 directly:
EP=$(make -s endpoint)
curl -s $EP/api/dev/handle -H 'content-type: application/json' \
  -d '{"user_id":"dev-user","text":"generate the report"}' | jq
```

---

## Verifying individual capabilities (deployed AgentBase or local)

The Impl 1 verification tooling extends naturally. `make seed` now also seeds registration statuses + feedback rows, so the report has data.

### Report (no Graph/Forms creds needed to see the card + audit)
```bash
make seed HOST_USER_ID=dev-user
EP=$(make -s endpoint)
curl -s $EP/api/dev/handle -H 'content-type: application/json' \
  -d '{"user_id":"dev-user","text":"focus on Demo Workshop"}' | jq -r '.reply'
curl -s $EP/api/dev/handle -H 'content-type: application/json' \
  -d '{"user_id":"dev-user","text":"generate the report"}' | jq
# → reply: "📊 Report ready — posted the card above. Confirm to email the summary…"
#   cards: [ report_card (metrics+summary+suggestions), confirm_card (action=mail) ]
```
Confirm the manager email with `/api/dev/confirm` (action `mail`, the emitted `pending_id`). With Graph creds + a workbook link (per-event `set_feedback_sources`, the global `FEEDBACK_WORKBOOK_URL`, or channel auto-discovery), the report first pulls fresh Form responses from that workbook.

### Ingestion / SharePoint (needs Graph creds + a real `team_id` for channel pull; link works from a URL alone)
- *"ingest the files in this channel"* → pulls the channel's SharePoint folder.
- *"ingest this file <SharePoint link>"* → resolves the link and ingests it.
- Either yields `documents` rows + extracted members/tasks, and (if anyone is unregistered) a proactive **invite** confirm card posted to the channel.

### Feedback jobs
```bash
venv/bin/python -c "from eventbuddy.scheduler.jobs import run_feedback_send; run_feedback_send('<event_id>')"
```
→ Forms link mailed individually (or clean no-config message) + a `scheduled_jobs`/`audit_log` row.

### Side effects (cloud DB)
```sql
SELECT action, tool_name, result FROM audit_log ORDER BY created_at DESC LIMIT 10;  -- report / mail / feedback_send
SELECT * FROM reports ORDER BY generated_at DESC LIMIT 1;
SELECT filename, parse_status FROM documents;
SELECT job_type, status FROM scheduled_jobs;
```

---

## Tests (58 new unit; 8 new integration)
**Unit:** [test_report_metrics.py](../tests/unit/test_report_metrics.py), [test_feedback_analyzer.py](../tests/unit/test_feedback_analyzer.py), [test_report_generation.py](../tests/unit/test_report_generation.py), [test_reporting_service.py](../tests/unit/test_reporting_service.py), [test_report_card.py](../tests/unit/test_report_card.py), [test_forms_sync.py](../tests/unit/test_forms_sync.py), [test_forms_endpoint.py](../tests/unit/test_forms_endpoint.py), [test_parsers.py](../tests/unit/test_parsers.py), [test_extractor.py](../tests/unit/test_extractor.py), [test_graph_files.py](../tests/unit/test_graph_files.py), [test_webhook_ingest.py](../tests/unit/test_webhook_ingest.py), [test_feedback_jobs.py](../tests/unit/test_feedback_jobs.py), [test_channel_files.py](../tests/unit/test_channel_files.py), [test_ingest_tool.py](../tests/unit/test_ingest_tool.py), [test_feedback_sources.py](../tests/unit/test_feedback_sources.py).
**Integration (Postgres):** [test_report_repositories.py](../tests/integration/test_report_repositories.py), [test_documents_repo.py](../tests/integration/test_documents_repo.py), [test_ingestion_pipeline.py](../tests/integration/test_ingestion_pipeline.py), [test_report_e2e.py](../tests/integration/test_report_e2e.py), [test_event_feedback_sources.py](../tests/integration/test_event_feedback_sources.py).

## Fixes (surfaced while running the live smoke tests)
- **Token counter** — `AgentRunner` now defaults the window trimmer to the model-agnostic `make_token_counter()` instead of the chat model; `langchain_openai`'s tiktoken counter raises `NotImplementedError` for vendor-namespaced MaaS model ids (`google/gemma-4-31b-it`). [runner.py](../src/eventbuddy/agent/runner.py)
- **Provisioning** — `EventRepository.create` now flushes so the `new_id` PK is assigned before `ProvisioningService` uses it for `set_channel`/`add_many` (previously crashed against a real DB with a NULL PK). [events.py](../src/eventbuddy/data/repositories/events.py)
- **Test isolation** — the LLM smoke tests `runner.reset(thread_id)` first; the integration conftest truncates Postgres but not the Redis checkpointer window, so a prior crash's orphaned tool-call could poison later runs.

---

## Notes / deferred
- **Deferred → sub-phase 2.4 (optional):** RAG/pgvector — embed doc/chat chunks, ground channel Q&A. `pgvector` dep + `Document` rows are present, so it's additive; the embeddings migration is the only one it would add.
- **MS Forms = Excel-workbook read** (chosen). No `formapi`. `/api/webhooks/forms` exists but is the unwired Power-Automate fallback.
- **Webhook→event mapping out of scope.** `/api/webhooks/graph` dedups + acks; mapping a drive-item notification to an `event_id` needs subscription metadata captured at subscription-creation time (manual for the demo). The **on-demand channel-files sync** is the fully-wired ingest path.
- **`team_id` vs `tenant_id`** (carried from Impl 1) — channel file pull + channel card posts reuse `settings.microsoft_app_tenant_id` as the Graph `team_id`; a real Teams `team_id` is needed for live channel operations. Link ingestion + the Forms workbook work from a URL alone (no `team_id`).
- **`.env.example`** — add `FEEDBACK_FORM_URL=` and `FEEDBACK_WORKBOOK_URL=` (the agent could not write that file; it lives outside the writable path).
- **Graph app permissions** — channel/workbook reads need app-only `Files.Read.All` + `Sites.Read.All` (admin consent); a deploy-time prerequisite. Without them every fetch degrades to "not available."
