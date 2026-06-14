# Implementation 2 — Intelligence Plane (implemented)

Status: **complete** on branch `impl-1-hitl-action-plane` (implemented 2026-06-13). 213 unit tests green (50 new), 6 new integration tests green against live Postgres, `ruff check src/ tests/` clean. App imports + `build_orchestrator()` build cleanly. *(Two pre-existing `test_llm_agent_smoke` failures are unrelated — `langchain_openai`'s tiktoken token-counter raises `NotImplementedError` for the configured model name `google/gemma-4-31b-it` in `pre_model_hook`; this fails on `main` too and never reaches Impl 2 code.)*

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
| Composition root | real `report_fn` + `ingest_fn`; threads them into the runner/tools | [agent/wiring.py](../src/eventbuddy/agent/wiring.py) |
| Tools | `generate_report` passes `user_id`; new `ingest_event_files` | [agent/tools.py](../src/eventbuddy/agent/tools.py) |
| Orchestrator | regex `GENERATE_REPORT` passes `user_id` | [agent/orchestrator.py](../src/eventbuddy/agent/orchestrator.py) |
| Webhook route | real notification handling (dedup → ack), keep token echo | [api/webhooks.py](../src/eventbuddy/api/webhooks.py) |
| Config | `feedback_form_url`, `feedback_workbook_url` | [config.py](../src/eventbuddy/config.py) |
| Main | mount `forms.router` | [main.py](../src/eventbuddy/main.py) |
| Deps | `openpyxl`, `python-docx`, `pypdf` | [pyproject.toml](../pyproject.toml) |
| Seed | + registration statuses + 2 feedback rows (report demo) | [scripts/seed.py](../scripts/seed.py) |

**No DB migration** — `documents`, `feedback_responses`, `reports`, `scheduled_jobs` already existed in [domain/models.py](../src/eventbuddy/domain/models.py). (RAG/pgvector — the one migration the plan flagged — is the deferred sub-phase 2.4 and is **not** built.)

---

## Verifying (deployed AgentBase or local)

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
Confirm the manager email with `/api/dev/confirm` (action `mail`, the emitted `pending_id`). With `FEEDBACK_WORKBOOK_URL` + Graph creds set, the report first pulls fresh Form responses from the workbook.

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

## Tests (50 new unit; 6 new integration)
**Unit:** [test_report_metrics.py](../tests/unit/test_report_metrics.py), [test_feedback_analyzer.py](../tests/unit/test_feedback_analyzer.py), [test_report_generation.py](../tests/unit/test_report_generation.py), [test_reporting_service.py](../tests/unit/test_reporting_service.py), [test_report_card.py](../tests/unit/test_report_card.py), [test_forms_sync.py](../tests/unit/test_forms_sync.py), [test_forms_endpoint.py](../tests/unit/test_forms_endpoint.py), [test_parsers.py](../tests/unit/test_parsers.py), [test_extractor.py](../tests/unit/test_extractor.py), [test_graph_files.py](../tests/unit/test_graph_files.py), [test_webhook_ingest.py](../tests/unit/test_webhook_ingest.py), [test_feedback_jobs.py](../tests/unit/test_feedback_jobs.py), [test_channel_files.py](../tests/unit/test_channel_files.py), [test_ingest_tool.py](../tests/unit/test_ingest_tool.py).
**Integration (Postgres):** [test_report_repositories.py](../tests/integration/test_report_repositories.py), [test_documents_repo.py](../tests/integration/test_documents_repo.py), [test_ingestion_pipeline.py](../tests/integration/test_ingestion_pipeline.py), [test_report_e2e.py](../tests/integration/test_report_e2e.py).

---

## Notes / deferred
- **Deferred → sub-phase 2.4 (optional):** RAG/pgvector — embed doc/chat chunks, ground channel Q&A. `pgvector` dep + `Document` rows are present, so it's additive; the embeddings migration is the only one it would add.
- **MS Forms = Excel-workbook read** (chosen). No `formapi`. `/api/webhooks/forms` exists but is the unwired Power-Automate fallback.
- **Webhook→event mapping out of scope.** `/api/webhooks/graph` dedups + acks; mapping a drive-item notification to an `event_id` needs subscription metadata captured at subscription-creation time (manual for the demo). The **on-demand channel-files sync** is the fully-wired ingest path.
- **`team_id` vs `tenant_id`** (carried from Impl 1) — channel file pull + channel card posts reuse `settings.microsoft_app_tenant_id` as the Graph `team_id`; a real Teams `team_id` is needed for live channel operations. Link ingestion + the Forms workbook work from a URL alone (no `team_id`).
- **`.env.example`** — add `FEEDBACK_FORM_URL=` and `FEEDBACK_WORKBOOK_URL=` (the agent could not write that file; it lives outside the writable path).
- **Graph app permissions** — channel/workbook reads need app-only `Files.Read.All` + `Sites.Read.All` (admin consent); a deploy-time prerequisite. Without them every fetch degrades to "not available."
