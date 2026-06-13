# Implementation 1 — HITL Action Plane (implemented)

Status: **complete** on branch `impl-1-hitl-action-plane` (implemented 2026-06-13). 163 unit tests green (34 new), `ruff check src/ tests/` clean. App imports + `build_orchestrator()` build cleanly. Verification tooling (`make seed` / `make smoke` / dev routes) in place; live Microsoft Graph sends + the Emulator/ngrok pass still pending.

This is the first of the two-implementation split (see the gap analysis). It turns EventBuddy from an agent that could only *talk and remember* into one that can **take confirmed actions in the world** — on command and on schedule — with an authorization gate and an audit trail. Implementation plan: [__plans__/08-impl1-hitl-action-plane.md](../__plans__/08-impl1-hitl-action-plane.md). Architecture references: §7.2/§7.3 (HITL flows), §9 (tools), §11 (security/PII), §12 (scheduling).

---

## What the agent can do now (as a Teams agent)

EventBuddy is a conversational tool-calling agent (LangGraph `create_react_agent`) with a three-layer memory stack (Phase 1.7), time-awareness + DM↔event cross-context recall (Phase 1.9), transparent tool-error surfacing (Phase 1.8), and a graceful regex fallback. On top of that, this implementation adds the **action plane**:

| # | Capability | Tool / surface | Gate | New here? |
|---|-----------|----------------|------|-----------|
| 1 | Create an event + provision its Teams channel + add the roster | `create_event` | host/moderator | — |
| 2 | Switch the focused event (DM also gets an event-context snapshot) | `set_focus_event` | any | — |
| 3 | Recall the focused event's shared discussion/decisions in a DM | `get_event_context` | member | — |
| 4 | List the caller's tasks in the focused event | `list_my_tasks` | member | — |
| 5 | **Update a task's status** (`todo`/`in_progress`/`done`) | `update_task` | own task, or moderator | **✅ new** |
| 6 | **Prepare reminders → confirm on a card → send** (Teams channel post or individual Outlook mail) | `prepare_reminders` + HITL card | host/moderator | **✅ now real** |
| 7 | **Draft a bulk email → confirm on a card → send** (individual Outlook sends) | `send_outlook_mail` + HITL card | host/moderator | **✅ new** |
| 8 | **Scheduled reminders** (D-3 / D-1 / H-1) fire out-of-band and send Outlook mail | APScheduler `run_reminder` | pre-authorized by schedule | **✅ now real** |
| — | Generate the AI report | `generate_report` | moderator | stub → Implementation 2 |

Cross-cutting, also new this implementation:
- **HITL confirmation loop** — destructive/bulk actions are *proposed* as an Adaptive Card; nothing sends until an authorized user clicks **Confirm**.
- **Audit trail** — every confirmed/denied/failed action writes an `audit_log` row (hash only — no PII).
- **Defense-in-depth authorization** — the confirm click is re-authorized server-side (clicker must be the preparer **and** still pass a role check); the card never carries identity or recipients.
- **PII protection (§11)** — reminders/mail send to **one recipient per message**, never a shared To/CC.
- **Durable schedule** — scheduled timers persist across restart (Postgres jobstore), with queryable `scheduled_jobs` rows.

> **Not wired into Teams yet.** There is no Azure Bot resource / Teams manifest in front of the runtime. The agent is **deployed on AgentBase** (public HTTPS URL); we point the **Bot Framework Emulator** at the deployed `/api/messages`, and use the synchronous **dev HTTP routes** for scriptable, ngrok-free verification. See the verification section below.

---

## The HITL loop (how a confirmed action flows)

```
User: "remind everyone who hasn't sent slides"
  └─ agent calls prepare_reminders  →  remind_fn:
        • loads the focused event's roster (recipients) from Postgres
        • stores a one-shot pending action in Redis  → opaque pending_id
        • emit_card(reminder_channel_card{pending_id})   ← side-channel
  └─ activity_router sends: text reply + the Adaptive Card (channel choice)

User clicks  [📧 Send via Outlook]   (Action.Submit → message activity w/ activity.value)
  └─ activity_router sees activity.value.action → ConfirmHandler (bypasses the agent)
        • pop(pending_id)              ← one-shot; replay sees nothing
        • re-authorize: clicker == requested_by  AND  role ≥ moderator
        • _perform_send(graph, payload, channel)   ← individual Outlook sends (PII §11)
        • audit_log.record(result = sent | failed | denied)
  └─ reply: "✅ Sent 4 Outlook reminder(s)."
```

The mechanism that lets a tool buried in the agent loop produce a card is a request-scoped **`TurnArtifacts` ContextVar** ([bot/turn_artifacts.py](../src/eventbuddy/bot/turn_artifacts.py)) — set by the router around `graph.invoke`, mirroring the Phase 1.8 `ToolTrace` pattern, so `Orchestrator.handle(...)` keeps its `-> str` contract.

---

## What changed (files)

| Piece | What it does | File |
|---|---|---|
| Cards-out side-channel | request-scoped `TurnArtifacts`; `emit_card` / `begin_artifacts` / `end_artifacts` | [bot/turn_artifacts.py](../src/eventbuddy/bot/turn_artifacts.py) *(new)* |
| Pending-action store | Redis, opaque one-shot tokens; `put`/`get`/`pop` (replay guard) | [agent/pending.py](../src/eventbuddy/agent/pending.py) *(new)* |
| Confirm handler | parse `activity.value` → re-auth decision → dispatch to executor → reply | [bot/confirm.py](../src/eventbuddy/bot/confirm.py) *(new)* |
| Audit repo | one `audit_log` row per action; payload **hash** only (no PII) | [data/repositories/audit.py](../src/eventbuddy/data/repositories/audit.py) *(new)* |
| Scheduled-job repo | durable `queued → sent/failed` rows, keyed by (event, job_type) | [data/repositories/scheduled_jobs.py](../src/eventbuddy/data/repositories/scheduled_jobs.py) *(new)* |
| Card builders | `pending_id` on the reminder card; generic `confirm_card` | [bot/cards/builders.py](../src/eventbuddy/bot/cards/builders.py) |
| Router wiring | `activity.value` → confirm branch; artifacts wrap; send card attachments | [bot/activity_router.py](../src/eventbuddy/bot/activity_router.py) |
| Composition root | real `remind_fn`, `update_task_fn`, `send_mail_fn`, membership `role_resolver`, `execute_confirmed_action`, module-level `_perform_send`; builds/attaches `ConfirmHandler` | [agent/wiring.py](../src/eventbuddy/agent/wiring.py) |
| Tools | `update_task` (direct), `send_outlook_mail` (HITL); `prepare_reminders` surfaces degraded messages | [agent/tools.py](../src/eventbuddy/agent/tools.py) |
| Role resolver | `RequestContext.role` reflects real `EventMember.role` when an event is focused | [agent/orchestrator.py](../src/eventbuddy/agent/orchestrator.py) |
| Scheduler | real `run_reminder` (Outlook + audit + status); opt-in `SQLAlchemyJobStore`; `scheduled_jobs` rows | [scheduler/jobs.py](../src/eventbuddy/scheduler/jobs.py), [scheduler/triggers.py](../src/eventbuddy/scheduler/triggers.py) |
| Config | `pending_action_ttl` (default 3600s) | [config.py](../src/eventbuddy/config.py) |
| Dev routes | `/api/dev/handle` returns emitted `cards`; new `/api/dev/confirm` runs `ConfirmHandler.resolve` (simulates a click, ngrok-free) | [api/dev.py](../src/eventbuddy/api/dev.py) |
| Seed script | idempotent demo event/members/tasks into `DATABASE_URL` | [scripts/seed.py](../scripts/seed.py) *(new)* |
| Smoke script | scripted end-to-end over the dev routes (local or deployed) | [scripts/smoke.sh](../scripts/smoke.sh) *(new)* |
| Make targets | `seed`, `seed-clean`, `smoke` (+ root forwarder) | [deployment/Makefile](../deployment/Makefile), [Makefile](../Makefile) |

No DB migration needed — `audit_log` and `scheduled_jobs` already existed in [domain/models.py](../src/eventbuddy/domain/models.py).

---

## Verifying a **deployed** agent (AgentBase public URL)

The runtime runs on AgentBase and points at the **cloud** Postgres/Redis (reachable directly over public TLS). That changes two things vs. local testing:

1. **Seeding targets the cloud DB.** `make seed` connects to the same `DATABASE_URL` the deployed runtime reads — so you seed test data from your laptop straight into the live DB the agent serves from. No shell into the container needed.
2. **The Emulator against a *remote* bot needs ngrok.** Bot Framework is async: the bot replies by calling back to the Emulator's `serviceUrl`. For a remote (AgentBase) bot to reach your local Emulator, the Emulator must expose itself via **ngrok** (Emulator → Settings → ngrok path). Without it you'll send a message and see *nothing* come back. The **dev HTTP routes are synchronous** (reply in the HTTP response), so they need **no ngrok and no Bot Framework auth** — which makes them the path of least resistance for a deployed agent, and fully scriptable.

> **Two creds tiers (unchanged).** *Without* Graph creds (`GRAPH_TENANT_ID`/`GRAPH_CLIENT_ID`/`GRAPH_CLIENT_SECRET`) every send **degrades cleanly** ("Couldn't send — Microsoft Graph isn't configured.") — enough to verify the whole card → confirm → audit loop. *With* valid Graph creds, confirms perform real Outlook/Teams sends.

> **Deploy prerequisite:** the runtime's env (`make deploy ENV_FILE=.env`) must have `DEV_ROUTES_ENABLED=true` for the dev routes (and the smoke target) to be mounted. Turn it off for a real production deployment.

### Make targets (added this implementation)

| Target | What it does |
|---|---|
| `make seed` | Seed the demo event **Demo Workshop** + 3 members + 3 tasks into `DATABASE_URL`. Idempotent (replaces on re-run). Override the owner with `make seed HOST_USER_ID=<id>`. |
| `make seed-clean` | Delete the demo event (cascades members + tasks). |
| `make smoke` | Run the full HITL flow over the dev routes against the deployed endpoint (or `make smoke URL=https://…`). |

`scripts/seed.py` and `scripts/smoke.sh` back these; both honor `--host-user-id` / `SMOKE_USER` so the seeded owner matches the identity you test as.

### Path A — scripted, ngrok-free (recommended for a deployed agent)

```bash
make seed HOST_USER_ID=dev-user        # populate the cloud DB
make smoke                             # uses `make endpoint` for the URL; SMOKE_USER=dev-user
#   ▶ reset / focus / my tasks / update task
#   ▶ prepare reminders   → captures the card's pending_id
#   ▶ confirm (outlook)   → "✅ Sent 3 Outlook reminder(s)." or the clean no-creds message
#   ▶ confirm again       → "…expired or was already handled…"  (replay guard)
```

`make smoke` exercises, end to end: focus → `list_my_tasks` → `update_task` (direct) → `prepare_reminders` (emits a card; the script reads `pending_id` from the JSON) → `/api/dev/confirm` (the new route that runs `ConfirmHandler.resolve` directly, simulating the click) → a second confirm to prove the one-shot replay guard. Drive individual steps by hand too:

```bash
EP=$(make -s endpoint)
curl -s $EP/api/dev/handle  -H 'content-type: application/json' \
  -d '{"user_id":"dev-user","text":"remind everyone about slides"}' | jq
# → {"reply":"… pick a channel on the card above.",
#    "cards":[{… "actions":[{… "data":{"action":"remind","channel":"outlook","pending_id":"<PID>"}}]}]}
curl -s $EP/api/dev/confirm -H 'content-type: application/json' \
  -d '{"user_id":"dev-user","action":"remind","channel":"outlook","pending_id":"<PID>"}' | jq
```
*(`/api/dev/confirm` re-auths the same way as a real click: `user_id` must equal the user who prepared the action.)*

### Path B — Bot Framework Emulator (for the real Adaptive Card UX)

1. `make seed HOST_USER_ID=<the User ID you'll set in the Emulator>`.
2. Emulator → **Settings** → set the **ngrok** path and enable "Run ngrok when the Emulator connects to a remote endpoint."
3. **Open Bot** → endpoint = `https://<agentbase-endpoint>/api/messages`; enter the deployed `MICROSOFT_APP_ID`/`MICROSOFT_APP_PASSWORD` (or leave blank if the runtime has none).
4. Emulator → **Settings** → set your **User ID** to match `HOST_USER_ID` from step 1 (so "my tasks"/focus resolve to you).
5. Walk the conversation and **click** the cards:

| Say | Expect |
|---|---|
| `focus on Demo Workshop` | "Focused on 'Demo Workshop'." (+ event-context snapshot in a DM) |
| `what are my tasks?` | the seeded task list |
| `mark Book the room as done` | "Updated 'Book the room' → done." (direct, no card) |
| `remind everyone about the slides` | a text line **and** an Adaptive Card with **💬 Teams** / **📧 Outlook** |
| click **📧 Send via Outlook** | "✅ Sent N Outlook reminder(s)." (or the clean no-Graph message) |
| click the **same** button again | "…expired or was already handled…" |
| `email the team: Doors open at 9am` | a confirm card → **✅ Confirm & send** |

### Check the side effects (cloud DB)
```sql
SELECT action, tool_name, result, actor_user_id, created_at FROM audit_log ORDER BY created_at DESC LIMIT 10;
SELECT job_type, status, scheduled_at FROM scheduled_jobs;
```
A confirmed send → `result = sent`; degraded → `failed`; an unauthorized click → `denied`.

### What to look for (acceptance)
- ✅ A reminder/mail request returns **text + a card**, not an immediate send.
- ✅ The card's button `data` carries only `{action, channel?, pending_id}` — **never** recipients or identity.
- ✅ Confirming once works; a second confirm of the same token is rejected (replay guard).
- ✅ Every confirm writes an `audit_log` row with the right `result`.
- ✅ With no Graph creds, sends degrade to a clean message (no 500, no crash).
- ✅ `update_task` mutates status directly with no card; ownership/role is enforced.

---

## Tests (34 new; 163 total; `pytest -q`, unit)
- [test_turn_artifacts.py](../tests/unit/test_turn_artifacts.py) — emit/collect, no-op off-path, per-turn isolation.
- [test_pending_store.py](../tests/unit/test_pending_store.py) — token round-trip, TTL applied, one-shot `pop`.
- [test_hitl_confirm.py](../tests/unit/test_hitl_confirm.py) — authorized send, expired, replay, wrong-user/low-role denial, Redis-down degrade.
- [test_perform_send.py](../tests/unit/test_perform_send.py) — channel routing + **individual** sends (PII §11), unknown action, no-channel miss.
- [test_action_tools.py](../tests/unit/test_action_tools.py) — `update_task`/`send_outlook_mail` wiring, schemas, role gates, `prepare_reminders` passthrough.
- [test_cards.py](../tests/unit/test_cards.py) — card data carries only the opaque token; `confirm_card` shape.
- [test_activity_router_hitl.py](../tests/unit/test_activity_router_hitl.py) — emitted card sent as attachment; `activity.value` routes to confirm and skips the agent.
- [test_scheduler.py](../tests/unit/test_scheduler.py) — injected reminder sender; errors swallowed (best-effort).
- [test_dev_route.py](../tests/unit/test_dev_route.py) — `/api/dev/handle` surfaces emitted cards; `/api/dev/confirm` delegates to the confirm handler and reports cleanly when unwired.

---

## Notes / deferred
- **Out of scope → Implementation 2:** document ingestion, `generate_report`, feedback dispatch jobs (`run_feedback_send`/`followup` stay stubs), RAG/pgvector, calendar invites, AgentBase Identity/Gateway/Memory.
- **Teams 1-1 personalized reminders** post to the **event channel** for now; true per-person 1-1 chat needs `GraphClient.create_or_get_chat(aad_id)` (deferred).
- **`team_id` vs `tenant_id`** — channel sends reuse `settings.microsoft_app_tenant_id` as the Graph `team_id` (consistent with existing provisioning wiring); these are not the same and a real Teams `team_id` is needed for live channel posts. Tracked follow-up; doesn't block Outlook sends or the card/confirm/audit loop.
- **`Action.Submit` assumption** — the confirm branch reads `activity.value` (the Teams `Action.Submit` shape). If a client sends an `invoke` (`adaptiveCard/action`) instead, add an `on_invoke_activity` handler alongside it. Verify in the Emulator (plan Step 0/8).
- **Deployed-runtime env** — the dev routes (`make smoke`, `/api/dev/*`) require `DEV_ROUTES_ENABLED=true` in the runtime's `.env` at deploy time; keep it **off** for a production-facing deployment (they bypass Bot Framework auth).
- **`.env.example`** — add `PENDING_ACTION_TTL=3600` (the agent could not write that file; it lives outside the writable path).
