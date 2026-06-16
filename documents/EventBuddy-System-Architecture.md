# EventBuddy — System Architecture & Developer Guide

> **Audience:** Engineers building EventBuddy.
> **Status:** v1.0 — baseline architecture for development.
> **Scope anchor:** The full EventBuddy vision (Teams-native, multi-event, document-ingesting AI assistant), justified by the pain points from the *Event Lifecycle Agent* proposal.

---

## 1. Overview & Goals

EventBuddy is an **event-centric AI assistant** for internal Event Organizer (EO) / EE / L&D teams, delivered as a **Microsoft Teams bot**. The team's recurring pain is that **every event costs 4–6 hours of manual overhead**, repeated monthly, across a fixed lifecycle: announce → distribute registration → chase registrations → remind before D-day → collect feedback → write a report.

EventBuddy collapses that into a single point of input. The EO describes an event once; the agent then drives the whole lifecycle: provisioning an isolated Teams workspace, ingesting planning documents, sending personalized omnichannel reminders, collecting feedback, and generating an **AI report with concrete suggestions for the next event**.

### Product goals

| Goal | Description |
|------|-------------|
| **Eliminate manual overhead** | Replace the repetitive 6-step flow with one-time input + agent automation. |
| **Multi-event isolation** | An EO runs 2–3 events at once; contexts must never bleed. `event_id` partitions everything. |
| **Proactive, not passive** | Agent watches uploaded documents and event state, then *suggests* the next action (Human-in-the-loop). |
| **Learn over time** | Feedback analysis + cross-event comparison produce actionable suggestions that improve the next event. |
| **Two collaboration scopes** | A shared per-event Teams channel *and* a private 1-1 personal assistant per user. |

### Non-goals (v1)

- Public/external-attendee event ticketing or payments.
- A standalone web UI (the product lives inside Teams; an admin web console is a future extension).
- Real-time video/streaming integration.
- Replacing Microsoft Forms/Planner — EventBuddy orchestrates them, it does not reimplement them.

---

## 2. Scope & Non-Goals (build phasing)

The architecture below describes the **whole system**. To stay shippable, build it in phases (see §18). The hackathon-critical slice is **Phase 1 + the report capability** — enough to demo broadcast → reminder → report end-to-end on AgentBase.

---

## 3. Glossary

| Term | Meaning |
|------|---------|
| **EO / EE** | Event Organizer / Employee Engagement team — the primary user. |
| **Event** | A single organized event with its own isolated context, channel, members, tasks. |
| **Channel scope** | The shared Teams channel auto-created per event; group collaboration happens here. |
| **Personal scope** | A user's private 1-1 chat with the bot; isolated, cross-event memory. |
| **Capability** | One lifecycle feature (Broadcast, Registration, Reminder, Feedback, Report, Provisioning). |
| **Tool** | A typed, agent-callable action (e.g. `send_outlook_mail`) exposed via the Resource Gateway. |
| **HITL** | Human-in-the-loop — destructive/bulk actions require an explicit confirmation click. |
| **MaaS** | Model-as-a-Service — GreenNode's OpenAI-compatible LLM endpoint. |
| **Gatekeeper** | The authorization component that checks a user's membership/role for an event before acting. |

---

## 4. High-Level Architecture

EventBuddy is an **event-driven, layered service** deployed as an AgentBase runtime. Three ingress paths feed a single bot core, which orchestrates an LLM agent that acts through a typed tool layer onto Microsoft 365 and the data stores.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          MICROSOFT 365 CLIENTS                                │
│   Teams (Channel scope)   Teams (Personal 1-1)   Outlook   MS Forms   OneDrive │
└───────────┬───────────────────┬──────────────────┬───────────┬───────────────┘
            │ Bot activities     │                  │ webhooks  │
            ▼                    ▼                  ▼           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  INGRESS (FastAPI)   /api/messages   /api/webhooks/graph   /api/health         │
└───────────────────────────────┬───────────────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  1. BOT GATEWAY / ADAPTER                                                      │
│     Bot Framework Adapter · Activity Router · Entra SSO · Permission Gatekeeper│
└───────────────────────────────┬───────────────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  2. AGENT ORCHESTRATION (LangGraph)                                            │
│     Intent routing · Dialog/Session Mgr (Redis) · Context-switching · Prompts  │
└───────────────────────────────┬───────────────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  3. TOOL / MCP LAYER  ── via AgentBase Resource Gateway (+ Policy enforcement) │
│     provision_channel · send_teams_msg · send_outlook_mail · create_invite     │
│     send_form · query_tasks · update_task · ingest_document · generate_report  │
└───────────────────────────────┬───────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────┬────────────────────────────────────┐
│  4. DOMAIN SERVICES                        │  5. INGESTION PIPELINE              │
│     Event · Member · Task · Reminder       │     Webhook → Graph download →      │
│     Feedback · Report                      │     parse (xlsx/docx/pdf) → LLM     │
│                                            │     structure → DB upsert + embed   │
└──────────────────────────────────────────┴────────────────────────────────────┘
                                 │
            ┌────────────────────┼────────────────────┬─────────────────────┐
            ▼                    ▼                    ▼                     ▼
┌────────────────┐   ┌────────────────────┐  ┌──────────────────┐  ┌───────────────┐
│ 6. LLM GATEWAY │   │ 7. SCHEDULER/WORKER │  │ 8. DATA LAYER     │  │ 9. INTEGRATIONS│
│ GreenNode MaaS │   │ reminders/escalation│  │ Postgres · Redis  │  │ MS Graph       │
│ chat/summ/embed│   │ feedback/report jobs│  │ pgvector          │  │ AgentBase I/L/M│
└────────────────┘   └────────────────────┘  └──────────────────┘  └───────────────┘
```

**Why event-driven + layered:** uploads, reminders, and webhooks all arrive asynchronously and must be processed without blocking the bot's request/response path. The scheduler/worker decouples time-based actions (reminders, follow-ups) from user interactions. Layers keep each concern independently testable and let the LangGraph agent reason over a small, well-bounded tool surface rather than the whole codebase.

---

## 5. Component Breakdown

Each component has one purpose, a defined interface, and explicit dependencies.

### 5.1 Bot Gateway / Adapter (`bot/`)
- **Does:** Receives Bot Framework activities, authenticates the caller (Entra SSO token), routes to the right handler, and runs the **Permission Gatekeeper** before any event-scoped action.
- **Interface:** `handle_activity(activity) -> Activity`; `gatekeeper.authorize(user_id, event_id, action) -> bool`.
- **Depends on:** Bot Framework SDK, Member service, Redis (turn state).
- **Key rule:** No event data is read or mutated until the gatekeeper confirms the `teams_user_id` exists in `event_members` for that `event_id` with sufficient role.

### 5.2 Agent Orchestration (`agent/`)
- **Does:** Holds a normal conversation and *invokes* event capabilities as **tools** via a LangGraph `create_react_agent` loop (LLM extracts the args); resolves the active event context (explicit channel `event_id` or personal-scope `current_event_id`); degrades to the deterministic regex router when LLM creds are absent or `agent_mode=regex`. *(See Phase 1.7 — `__plans__/05-phase1.7-conversational-agent.md`.)*
- **Interface:** `agent.run(turn_context, session) -> AgentResult`.
- **Depends on:** `ChatOpenAI` → MaaS, Tool layer, the layered memory (Redis + Postgres).
- **Sub-parts:** `runner.py` (`create_react_agent` behind a factory), `tools.py` (`@tool` wrappers, identity injected server-side), `memory.py` (Redis checkpointer + per-thread lock), `transcript.py` / `summarizer.py` (Postgres transcript + rolling summary), `intents.py` (regex fallback), `session.py` (Redis-backed `UserSession` app-state), `prompts/`.
- **Layered memory (session-scoped):** each request binds to a `thread_id` — `event:{event_id}` for a **shared** channel/event session, `dm:{user_id}` for a **private** 1-1. Three layers: (1) **Redis working window** = LangGraph checkpointer holding the live message graph *with tool-call/result pairs intact*, trimmed to **≤4096 tokens** on user/assistant boundaries, 24h TTL; (2) **Postgres `conversation_messages`** = durable user/assistant transcript (tool noise dropped), the overflow + rehydration source — Redis-first, then Postgres; (3) **Postgres `session_summaries`** = rolling per-session summary of older turns, refreshed by a background APScheduler job, injected so long events keep early context within the 4096 budget. Shared `event:` threads tag each turn with the speaker and serialize concurrent runs with a per-thread Redis lock.

### 5.3 Tool / MCP Layer (`agent/tools/`)
- **Does:** Exposes every agent action as a **typed tool** with a JSON schema. Tools are registered as targets behind the **AgentBase Resource Gateway**, which enforces inbound auth and per-action **Policy** (e.g. only `host`/`moderator` may trigger bulk mail).
- **Interface:** Each tool = `name`, `input schema`, `output schema`, `handler`. The agent calls tools via function-calling; the Gateway proxies and authorizes.
- **Depends on:** Domain services, Integration layer, Policy.

### 5.4 Domain Services (`domain/`, `capabilities/`)
Pure business logic, no I/O framework concerns. One module per aggregate:
- **Event** — lifecycle/status (`ideation → planning → running → wrap_up`), provisioning orchestration.
- **Member** — roster, roles, registration status.
- **Task** — task CRUD, due-date queries, per-assignee filtering.
- **Reminder** — scheduling rules (D-3/D-1/H-1), escalation thresholds.
- **Feedback** — response intake, sentiment/theme analysis.
- **Report** — metrics aggregation, summary + suggestion generation.

`capabilities/` composes these services + tools into the six user-facing features.

### 5.5 Ingestion Pipeline (`ingestion/`)
- **Does:** On a SharePoint/OneDrive `FileCreated`/`FileUpdated` webhook, downloads the file via Graph, parses by MIME type, sends raw text/tables to the LLM for structuring, upserts the result into Postgres, and embeds chunks into pgvector.
- **Interface:** `pipeline.ingest(drive_item_id, event_id) -> IngestResult`.
- **Depends on:** Graph client, parsers (`openpyxl`, `python-docx`, `pdfplumber`), LLM gateway, Task/Member services, vector store.

### 5.6 LLM Gateway (`integrations/llm/`)
- **Does:** Single abstraction over GreenNode MaaS for `chat()`, `summarize()`, `embed()`. Selects model per task (Gemma-4-31b for chat/extraction, Qwen-3-27B for summarization/suggestions). Centralizes retries, timeouts, token budgeting, and prompt assembly.
- **Interface:** `llm.chat(messages, model=?) `, `llm.embed(texts)`, `llm.summarize(text, style)`.
- **Depends on:** AgentBase LLM API key (OpenAI-compatible endpoint).

### 5.7 Scheduler / Worker (`scheduler/`)
- **Does:** Runs time-based jobs out-of-band from the bot request path: registration-rate checks + escalation, D-3/D-1/H-1 reminders, post-event feedback dispatch + 24h follow-up, delayed report generation.
- **Interface:** `enqueue(job_type, event_id, run_at, payload)`; worker consumes from Redis.
- **Depends on:** Redis (queue), Domain services, Tool layer.
- **Tech:** APScheduler for cron-style triggers + a Redis-backed job queue (RQ/Celery) for durable execution.

### 5.8 Data Layer (`data/`)
- **Does:** Owns persistence. SQLAlchemy + Alembic for Postgres, a Redis client for session/queue/cache, and a pgvector-backed vector store. Exposes **repositories** so domain code never writes raw SQL.
- **Interface:** `repositories.events`, `.members`, `.tasks`, … each with typed methods.

### 5.9 Integration Layer (`integrations/`)
- **MS Graph client** — Teams (channels, messages, Adaptive Cards), Outlook mail, Calendar invites, Forms, Files/SharePoint webhooks.
- **AgentBase Identity** — stores & refreshes the app's MS Graph OAuth2 token (outbound auth), so the codebase never persists raw secrets.
- **AgentBase Memory (optional)** — semantic recall for the personal-scope assistant.
- **AgentBase Resource Gateway** — fronts the tool layer.

---

## 6. Data Architecture

### 6.1 Entity-Relationship (Postgres)

```
events 1───∞ event_members
  │  1            
  ├──────∞ tasks            (assignee_id ─→ event_members.teams_user_id)
  ├──────∞ documents
  ├──────∞ scheduled_jobs
  ├──────∞ feedback_responses
  ├──────∞ idea_summaries
  └──────1 reports (one current report per event; history kept by generated_at)
audit_log ∞───1 events       (every HITL-confirmed action recorded)
```

All event-scoped tables carry `event_id` (FK → `events.event_id`) as a **mandatory** column; every query in event context appends `WHERE event_id = :id`.

### 6.2 Table specifications

**`events`**
| Column | Type | Notes |
|--------|------|-------|
| `event_id` | UUID PK | |
| `event_name` | VARCHAR(255) NOT NULL | |
| `teams_channel_id` | VARCHAR(100) UNIQUE | null until provisioned |
| `status` | VARCHAR(20) | `ideation` \| `planning` \| `running` \| `wrap_up` |
| `objective` | TEXT | |
| `start_at` / `end_at` | TIMESTAMPTZ | |
| `location` | VARCHAR(255) | room or meeting link |
| `registration_link` | VARCHAR(500) | |
| `host_user_id` | VARCHAR(100) | FK-ish → event_members |
| `created_at` / `updated_at` | TIMESTAMPTZ | default `now()` |

**`event_members`**
| Column | Type | Notes |
|--------|------|-------|
| `mapping_id` | UUID PK | |
| `event_id` | UUID FK | |
| `teams_user_id` | VARCHAR(100) NOT NULL | |
| `email` | VARCHAR(255) NOT NULL | |
| `display_name` | VARCHAR(255) | |
| `role` | VARCHAR(20) | `host` \| `moderator` \| `member` |
| `registration_status` | VARCHAR(20) | `pending` \| `registered` \| `declined` |
| `registered_at` | TIMESTAMPTZ | |
| | | UNIQUE(`event_id`, `teams_user_id`) |

**`tasks`**
| Column | Type | Notes |
|--------|------|-------|
| `task_id` | UUID PK | |
| `event_id` | UUID FK | |
| `task_name` | TEXT NOT NULL | |
| `assignee_id` | VARCHAR(100) | → event_members.teams_user_id |
| `assignee_email` | VARCHAR(255) | for external speakers w/o Teams id |
| `due_date` | TIMESTAMPTZ | |
| `status` | VARCHAR(20) | `todo` \| `in_progress` \| `done` |
| `source_document` | VARCHAR(500) | OneDrive path that produced this task |

**`documents`**
| Column | Type | Notes |
|--------|------|-------|
| `doc_id` | UUID PK | |
| `event_id` | UUID FK | |
| `filename` | VARCHAR(500) | |
| `drive_item_id` | VARCHAR(200) | Graph item id |
| `mime_type` | VARCHAR(100) | |
| `parse_status` | VARCHAR(20) | `pending` \| `parsed` \| `failed` |
| `ingested_at` | TIMESTAMPTZ | |

**`chat_files`** (Impl 9 — per-chat file catalog; the intelligence-plane analogue of `documents` for **group-chat / 1-1 DM** files, which have no Team/SharePoint backing)
| Column | Type | Notes |
|--------|------|-------|
| `file_id` | UUID PK | |
| `chat_id` | VARCHAR(200) | the conversation id (`19:…@thread.v2` group / `a:…` DM) — **no FK to events** |
| `filename` | VARCHAR(500) | |
| `share_url` | VARCHAR(1000) | the file's OneDrive/SharePoint sharing URL (a chat attachment's `contentUrl`) |
| `drive_item_id` | VARCHAR(200) | resolved from `share_url` on first read; idempotency key with `chat_id` |
| `summary` / `doc_type` | TEXT / VARCHAR(40) | filled lazily on first list/read |
| `parse_status` | VARCHAR(20) | `reference` (captured, not yet read) \| `parsed` \| `failed` |
| `synced_at` | TIMESTAMPTZ | |

A row is created the moment a file is shared (a cheap `reference` upsert — `share_url` + `filename`, no download), so a file named/described on a *later* turn still resolves even though the share link rides only the activity that bore it. Discovery is lazy and user-driven (no auto-ingest / on-join hook): a group chat scans `/chats/{id}/messages` + current attachments; a **1-1 DM uses attachments only** (a bot DM has no Graph chat — `/chats/{a:…}` is never called). The agent resolves a file by **name/description** against this catalog; on an ambiguous match it posts a multi-select dropdown picker whose submit re-enters the agent to read the chosen file(s) and answer the original question.

**`scheduled_jobs`**
| Column | Type | Notes |
|--------|------|-------|
| `job_id` | UUID PK | |
| `event_id` | UUID FK | |
| `job_type` | VARCHAR(40) | `reg_check` \| `reminder_d3` \| `reminder_d1` \| `reminder_h1` \| `feedback_send` \| `feedback_followup` \| `report` |
| `target` | JSONB | recipients / scope |
| `channel` | VARCHAR(20) | `teams` \| `outlook` |
| `scheduled_at` | TIMESTAMPTZ | |
| `status` | VARCHAR(20) | `queued` \| `sent` \| `cancelled` \| `failed` |

**`feedback_responses`**
| Column | Type | Notes |
|--------|------|-------|
| `response_id` | UUID PK | |
| `event_id` | UUID FK | |
| `respondent_id` | VARCHAR(100) | nullable (anonymous) |
| `raw_payload` | JSONB | original Forms answers |
| `sentiment` | VARCHAR(20) | `positive` \| `neutral` \| `negative` |
| `themes` | JSONB | LLM-extracted theme tags |
| `submitted_at` | TIMESTAMPTZ | |

**`reports`**
| Column | Type | Notes |
|--------|------|-------|
| `report_id` | UUID PK | |
| `event_id` | UUID FK | |
| `metrics_json` | JSONB | attendance/registration/response rates, scores |
| `summary_md` | TEXT | AI-summarized feedback themes |
| `suggestions_md` | TEXT | AI-generated next-event action items |
| `generated_at` | TIMESTAMPTZ | |

**`idea_summaries`** — `summary_id`, `event_id`, `source` (`chat`), `content_md`, `created_at`. Stores brainstorm-synthesis output.

**`audit_log`** — `log_id`, `event_id`, `actor_user_id`, `action`, `tool_name`, `payload_hash`, `result`, `created_at`. Records every HITL-confirmed action for traceability.

**`conversation_messages`** — `id`, `thread_id` (`event:{event_id}` \| `dm:{user_id}`), `event_id?`, `role` (`user`\|`assistant`), `speaker_name?`, `content`, `created_at`. Durable transcript layer (layer 2): user/assistant turns only — tool calls/results are **not** stored. Overflow target when the Redis working window is trimmed, and the rehydration source on a Redis miss. Indexed by `(thread_id, created_at)`.

**`session_summaries`** — `thread_id` (pk), `summary`, `covered_through`, `updated_at`. Rolling long-term memory (layer 3): a compact running summary of turns older than the rehydration tail, refreshed by the background `summarize_session` job and injected as context so long-running event sessions retain early context within the 4096-token budget.

### 6.3 Redis (ephemeral state)
| Key pattern | Purpose | TTL |
|-------------|---------|-----|
| `session:{teams_user_id}` | `UserSession`: `current_event_id`, dialog state, last intent | 24h sliding |
| `checkpoint:{thread_id}` | LangGraph working window (live message graph + tool pairs, ≤4096 tok); `thread_id` = `event:{event_id}` \| `dm:{user_id}` | 24h |
| `lock:{thread_id}` | Per-session lock serializing concurrent runs on a shared `event:` thread | seconds |
| `turn:{conversation_id}` | Bot Framework per-turn state | minutes |
| `webhook:dedup:{notification_id}` | Drop duplicate Graph notifications | 1h |
| `ratelimit:{user}:{action}` | Throttle reminders/mail | window |
| `queue:jobs` | Worker job queue (RQ/Celery) | — |

### 6.4 Vector store (pgvector)
- One embeddings table: `(chunk_id, event_id, source_type [doc|chat], drive_item_id, text, embedding vector(N), metadata jsonb)`.
- **Isolation:** every similarity query is filtered by `event_id` (metadata filter), mirroring the SQL `WHERE event_id` rule, so RAG never leaks across events.
- Used by the personal-scope assistant and channel Q&A to ground answers in that event's documents and discussion.

---

## 7. Key Flows

### 7.1 Event creation & channel provisioning

The team leader creates an event **from their private 1-1 chat** with EventBuddy (not from inside a channel). They name the event and supply the member roster as a list of emails and/or whole domains to include.

```
(1-1 DM) Leader: "create event 'AI Workshop' members: a@x.com, b@x.com, @team.com"
 → Gatekeeper: caller may create events → allow
 → Agent intent: CREATE_EVENT          → tool: provision_channel
 → Event service: INSERT events(status=ideation)
 → Graph: create Teams channel, add the EventBuddy app + members, pin overview card
 → Member service: INSERT event_members(role=host/member, registration=pending)
 → Reply (in the DM): "Channel created — here's the overview" + deep link to the channel
```

**Two entry paths to a channel↔event binding:**

| Path | How | History |
|------|-----|---------|
| **A — agent-provisioned (primary)** | Leader runs the DM command above; the agent calls `create_channel` and adds itself + members. | No gap: the app is present from message #1. |
| **B — manually-created channel** | A human makes the channel and adds the EventBuddy app via Teams' *Add an app*, then runs `bind this channel to <event>` (or the leader created it via path A). | ⚠ **A bot only receives messages sent *after* it was added.** Prior history is not delivered through the Activity feed. To backfill it, the app needs Graph `ChannelMessage.Read.All` via **RSC** (`channel.getAllMessages`) — a *protected* API requiring E5 / metered billing. Default stance: **add the app at channel creation** (path A) so there is no gap; treat history backfill as an optional, license-gated enhancement. |

`events.teams_channel_id` (unique, nullable) is the binding key for both paths.

### 7.2 Document ingestion → proactive suggestion (HITL)
```
Someone uploads Danh_sach_khach_moi.xlsx to the channel
 → Graph webhook FileCreated → /api/webhooks/graph (dedup via Redis)
 → ingestion.pipeline: download → openpyxl parse → LLM structure (JSON)
 → detects 50 invitees with empty "invitation status"
 → INSERT documents + tasks/members; embed chunks → pgvector
 → Agent posts Adaptive Card: "50 guests not yet invited. Send invites via Outlook?"
 → EO clicks [Confirm]  → Policy check (role ≥ moderator)
 → tool: send_outlook_mail (bulk) → audit_log entry
```

### 7.3 Omnichannel smart reminder
```
EO: "@EventBuddy remind whoever hasn't submitted slides"
 → Task service: find tasks status≠done near due_date
 → Agent groups by recipient type → Adaptive Card with channel choice:
     • internal Huy   → [Teams Chat]  → personalized 1-1 message
     • external speaker → [Outlook]   → LLM-drafted formal email (hides internal addresses)
 → action requires click (HITL) → execute → audit_log
```

### 7.4 Smart escalation (scheduler-driven)
```
scheduled_job reg_check fires (e.g. D-? daily)
 → Member service: registration_rate(event_id)
 → if rate < 50% after 2 days:
      • alert EO team in channel
      • increase reminder frequency for pending members
```

### 7.5 Feedback → AI report
```
Event end_at passes → job feedback_send → Forms link to attendees
 → +24h job feedback_followup → nudge non-responders
 → on enough responses (or job report): 
      Feedback service: per-response sentiment + themes (LLM)
      Report service: aggregate metrics + Qwen summarize + suggestions
      INSERT reports; post report card to channel; draft summary email to manager
```

### 7.6 Personal-scope context switching
```
DM: "create event 'AI Workshop' members: a@x.com, @team.com"  → provisions channel (§7.1 path A)
DM: "focus on AI Workshop"   → session.current_event_id = <id>  (Redis)
DM: "what tasks are due soon?"
 → all task queries + RAG implicitly filtered WHERE event_id = current_event_id
DM (no focus set): "my tasks?" → aggregate across all events the user belongs to
DM (no event match): general assistant / small talk
```
The private 1-1 chat is both the **control plane** (leaders provision events and switch focus here) and a **general-purpose assistant** (everyday questions, plus event/task queries scoped to the focused event).

---

## 8. Agent Orchestration (LangGraph)

The agent is an **LLM tool-calling loop** (`create_react_agent`, Phase 1.7), not a fixed
classifier. Per request:

1. **Build server context** — the orchestrator resolves identity/role/scope/focused-event into a `RequestContext` and the scope-aware `thread_id`. Identity is **never** a model-settable tool arg.
2. **Run the ReAct loop** — the model chats normally and emits `tool_calls` only when the user wants an event action, extracting the arguments itself (replacing the old regex `classify()`, which remains the graceful fallback). The `pre_model_hook` trims the working window to ≤4096 tokens on user/assistant boundaries before each LLM call.
3. **Enforce permissions in code** — mutating tools (`create_event`, `prepare_reminders`) run the `Gatekeeper`/role check *inside the tool body*; the model never decides authorization. Role is scope-dependent (`_default_role` + the wiring `role_resolver`): a **1-1 DM** caller resolves to `host`; a **group chat is a flat peer space** — every participant resolves to `moderator` regardless of any focused event / `EventMember` row, so anyone can run the privileged actions (outbound sends still pass the HITL confirm card); a **channel** uses the caller's real `EventMember.role` (defaulting to `member`).
4. **Ground & respond** — the reply is built on real tool results (no fabricated event names/ids); on LLM failure or `agent_mode=regex` the orchestrator degrades to the deterministic Phase 1 router.

> HITL bulk/destructive flows (Adaptive Card propose → confirm activity) remain handled by the activity router, unchanged by Phase 1.7.

**Conversation memory** is session-scoped and layered — Redis working window (≤4096 tok, tool pairs intact, 24h TTL) → Postgres `conversation_messages` transcript (user/assistant only; overflow + rehydration) → Postgres `session_summaries` rolling summary (background job). `thread_id` = `event:{event_id}` for a shared channel session, `dm:{user_id}` for a private 1-1. See §5.2 and `__plans__/05-phase1.7-conversational-agent.md`.

**Session & context-switching:** `UserSession` (Redis) holds `current_event_id` + dialog state. Per the design rule:

```
C(U, t) = f( Redis_session(U), match_event_id(Q) )
  if Q explicitly switches context → session.current_event_id = ID_X
  if session.current_event_id set  → inject WHERE event_id = ID_X into every query & RAG filter
```

**Prompting:** system prompts live in `agent/prompts/`. The document-structuring prompt forces JSON-only output (e.g. `{task_name, assignee_email, due_date}` arrays) so the ingestion pipeline can parse deterministically.

---

## 9. Tool / MCP Layer & Resource Gateway

Every agent action is a typed tool. Tools are registered as **targets on the AgentBase Resource Gateway**, which provides inbound auth (IAM/JWT) and **Policy** enforcement before a tool runs.

| Tool | Input (summary) | Guard |
|------|-----------------|-------|
| `provision_channel` | event_name, members | EO role |
| `send_teams_message` | user_id, text/card | member of event |
| `send_outlook_mail` | recipients, subject, body | role ≥ moderator; **HITL for bulk** |
| `create_calendar_invite` | attendees, when, location | role ≥ moderator |
| `send_feedback_form` | event_id, audience | role ≥ moderator |
| `query_tasks` | filters (assignee, due, status) | member of event |
| `update_task` | task_id, status | member (own task) or moderator |
| `ingest_document` | drive_item_id | system/webhook |
| `generate_report` | event_id | role ≥ moderator |

**Policy examples (authored in AgentBase Policy):** deny `send_outlook_mail` with `recipients.count > 1` unless `principal.role in [host, moderator]` and a signed confirmation payload is present; deny any tool whose `event_id` the principal is not a member of.

---

## 10. External Integrations

### Microsoft Graph (via `integrations/graph/`)
| Capability | Graph surface | Permission (app/delegated) |
|------------|---------------|----------------------------|
| Create channel, add members, post/pin cards | Teams / Channels / chatMessages | `Channel.Create`, `ChannelMessage.Send`, `TeamMember.ReadWrite` |
| Send 1-1 Teams message | Chats / chatMessages | `Chat.ReadWrite` |
| Send email | Mail.Send | `Mail.Send` |
| Calendar invite | Events | `Calendars.ReadWrite` |
| Feedback form | Forms (or templated link) | per Forms availability |
| File webhooks + download | Drive / subscriptions | `Files.Read.All`, `Sites.Read.All` |

- Auth via **Entra ID OAuth2**; tokens are stored & refreshed by **AgentBase Identity**, not in the app.
- File-change subscriptions must be renewed before expiry (a `subscription_renew` scheduled job).

### AgentBase
- **LLM** — OpenAI-compatible MaaS endpoint + key; models selected per task in the LLM gateway.
- **Identity** — outbound MS Graph token provider.
- **Memory (optional)** — semantic memory for personal-scope recall.
- **Resource Gateway + Policy** — tool fronting + authorization.
- **Runtime + Monitor** — hosting + logs/metrics.

---

## 11. Security & Authorization

- **Authentication:** Entra ID OAuth2 (Teams SSO). Bot validates the inbound token; outbound Graph calls use AgentBase Identity-managed tokens.
- **Authorization (Gatekeeper):** before any event-scoped action, verify `teams_user_id ∈ event_members(event_id)` with sufficient `role`. Enforced twice — in the bot Gatekeeper *and* in Resource Gateway Policy (defense in depth).
- **Human-in-the-loop guardrail:** the agent may **never** auto-execute bulk mail, mass notifications, or deletions. These require a signed Adaptive Card confirmation from an authorized EO. Enforced by Policy + recorded in `audit_log`.
- **Data isolation:** `event_id` filtering on every SQL query and vector search prevents cross-event leakage; personal-scope DMs only surface events the user belongs to.
- **Secrets:** no raw credentials in the repo or DB — API keys/tokens come from AgentBase Identity/LLM and environment config.
- **PII:** internal email addresses are never exposed to external speakers (the mail tool sends individually, not via shared To/CC).

---

## 12. Scheduling & Background Jobs

Time-based work runs in the **worker**, decoupled from the bot request path:

| Job | Trigger | Action |
|-----|---------|--------|
| `reg_check` | daily until registration closes | escalate if rate < threshold |
| `reminder_d3 / d1 / h1` | computed from `start_at` | send reminders (Teams + Outlook) |
| `feedback_send` | at `end_at` | dispatch Forms link |
| `feedback_followup` | end_at + 24h | nudge non-responders |
| `report` | after feedback window | generate report + draft email |
| `subscription_renew` | before Graph subscription expiry | renew file webhooks |

Jobs are persisted in `scheduled_jobs` (durable, queryable) and executed via a Redis-backed queue; APScheduler converts event timestamps into concrete run times.

---

## 13. Codebase Structure

```
eventbuddy/
├── README.md
├── pyproject.toml                # deps, tooling (ruff, mypy, pytest)
├── Dockerfile                    # builds the AgentBase runtime image
├── docker-compose.yml            # local: app, worker, postgres, redis
├── .env.example
├── alembic.ini · alembic/        # DB migrations
├── docs/
│   └── architecture.md           # this document (or a link to it)
├── src/eventbuddy/
│   ├── main.py                   # FastAPI app factory + lifespan
│   ├── config.py                 # pydantic-settings (env-driven)
│   ├── api/
│   │   ├── messages.py           # POST /api/messages (Bot Framework)
│   │   ├── webhooks.py           # POST /api/webhooks/graph
│   │   └── health.py
│   ├── bot/
│   │   ├── adapter.py            # CloudAdapter setup
│   │   ├── activity_router.py    # dispatch by activity type/scope
│   │   ├── auth.py               # SSO + Permission Gatekeeper
│   │   └── cards/                # Adaptive Card builders
│   ├── agent/
│   │   ├── graph.py              # LangGraph state machine
│   │   ├── intents.py            # intent classification
│   │   ├── session.py            # Redis-backed UserSession + context switch
│   │   ├── prompts/              # system & task prompt templates
│   │   └── tools/                # typed tool defs + registry
│   ├── capabilities/             # composes services+tools into features
│   │   ├── provisioning.py
│   │   ├── broadcast.py
│   │   ├── registration.py
│   │   ├── reminders.py
│   │   ├── feedback.py
│   │   └── reporting.py
│   ├── domain/
│   │   ├── models.py             # SQLAlchemy ORM
│   │   ├── schemas.py            # pydantic DTOs
│   │   ├── events.py · members.py · tasks.py
│   │   ├── reminders.py · feedback.py · reports.py
│   ├── ingestion/
│   │   ├── pipeline.py
│   │   ├── parsers/              # xlsx.py · docx.py · pdf.py
│   │   └── extractor.py          # LLM structuring → JSON
│   ├── integrations/
│   │   ├── graph/                # teams.py · mail.py · calendar.py · forms.py · files.py
│   │   ├── llm/                  # client.py · models.py · prompts glue
│   │   ├── agentbase/            # identity.py · memory.py · gateway.py
│   │   └── vector.py             # pgvector store + RAG retrieval
│   ├── scheduler/
│   │   ├── worker.py             # queue consumer entrypoint
│   │   ├── jobs.py               # job handlers
│   │   └── triggers.py           # APScheduler → scheduled_jobs
│   ├── data/
│   │   ├── db.py                 # engine/session
│   │   ├── redis.py
│   │   └── repositories/         # events.py · members.py · tasks.py · ...
│   └── common/
│       ├── logging.py · errors.py · security.py · ids.py
├── tests/
│   ├── unit/                     # domain services, parsers, prompt builders
│   ├── integration/              # repositories, graph client (mocked), pipeline
│   └── e2e/                      # full turn: activity → response (test adapter)
└── scripts/                      # seed data, local dev helpers
```

**Boundaries:** `api/` and `bot/` know nothing about SQL; `domain/` knows nothing about Bot Framework; `integrations/` is the only place that talks to external systems; `capabilities/` is the seam where the two meet. This keeps each layer independently testable and swappable.

---

## 14. Configuration & Secrets

All config is environment-driven via `pydantic-settings` (`config.py`). `.env.example` documents every key:

| Var | Purpose |
|-----|---------|
| `MICROSOFT_APP_ID` / `MICROSOFT_APP_PASSWORD` | Bot Framework identity |
| `GRAPH_TENANT_ID` | Entra tenant |
| `AGENTBASE_IDENTITY_*` | outbound Graph token provider |
| `AGENTBASE_LLM_BASE_URL` / `AGENTBASE_LLM_API_KEY` | MaaS endpoint + key |
| `LLM_CHAT_MODEL` / `LLM_SUMMARY_MODEL` / `LLM_EMBED_MODEL` | model selection |
| `DATABASE_URL` | Postgres DSN |
| `REDIS_URL` | session + queue |
| `GATEWAY_URL` | AgentBase Resource Gateway endpoint |
| `WEBHOOK_PUBLIC_URL` | public base for Graph subscriptions |

Secrets are never committed; in production they come from AgentBase Identity/LLM and runtime env injection.

---

## 15. Deployment on AgentBase

### 15.1 The platform contract & mental model

AgentBase Runtime is a **generic container host**. For a **Custom Agent** (we write the code), it enforces exactly two things:

1. The container **listens on port `8080`** — all inbound traffic is routed there.
2. It exposes **`GET /health`** returning HTTP 200 when ready — used to mark the runtime `ACTIVE`.

Everything else (routes, payloads) is ours to define. AgentBase returns a **public HTTPS endpoint URL** (PUBLIC network mode) that fronts the container.

> **EventBuddy is a Custom Agent, not an OpenClaw.** OpenClaw templates only support Telegram/Zalo — there is no Teams template — so we ship our own Docker image. The SDK's `/invocations` convention does **not** apply; we serve our own routes (`/api/messages`, `/api/webhooks/graph`, `/health`), which the platform fully allows.

### 15.2 How Teams connects to the AgentBase endpoint

AgentBase only provides hosting + a public URL. Microsoft owns the Teams↔bot transport. Teams never calls the container directly:

```
Teams client → Azure Bot Service (Bot Connector) → AgentBase public endpoint → container :8080 /api/messages
```

Two registrations live **outside** AgentBase, in the Microsoft tenant:

- **Azure Bot resource** (Entra app: `MICROSOFT_APP_ID` + secret). Its *Messaging endpoint* is set to `https://<agentbase-endpoint>/api/messages`.
- **Teams app manifest** — the package uploaded/sideloaded into Teams. References the bot App ID and declares scopes (team/channel + personal 1-1).

The AgentBase endpoint URL is the glue: it becomes the bot's messaging endpoint and the Graph webhook `notificationUrl` (`.../api/webhooks/graph`).

### 15.3 Interaction model (asynchronous)

Bot Framework is **not** request/response. When a user types in Teams:

1. Teams → Azure Bot Service → `POST /api/messages` (carries an `Activity` + `serviceUrl`).
2. The container returns `200 OK` immediately — an **ack**, not the reply.
3. To reply, the container **calls back out** to the Bot Connector at `serviceUrl` using the bot app credentials. Proactive messages (reminders, escalation) reuse the same outbound path via a stored `conversationReference`.

Consequence for our design: replies *and* all scheduled reminders are **outbound calls from the container to Microsoft**, so the scheduler/worker can message users with no inbound trigger.

### 15.4 Credential directions

| Direction | Mechanism |
|-----------|-----------|
| Inbound (Teams → us) | Validate Bot Framework JWT on `/api/messages` using `MICROSOFT_APP_ID`. |
| Outbound to Microsoft (replies, Graph channels/mail/calendar) | Bot replies use bot app creds; Graph calls use the Entra OAuth2 token managed by **AgentBase Identity**. |
| Outbound to platform (MaaS LLM, Memory) | AgentBase auto-injects `GREENNODE_CLIENT_ID/SECRET/AGENT_IDENTITY/ENDPOINT_URL`; the SDK uses these. **Never set them in `.env`.** |

### 15.5 Deploy steps

1. **Build** the image for `linux/amd64` (see Dockerfile, §19.5). Container serves `/health`, `/api/messages`, `/api/webhooks/graph` on port 8080; the APScheduler worker runs **in-process** (simplest for the hackathon) or as a second runtime later.
2. **Push** to the AgentBase managed Container Registry: `vcr.vngcloud.vn/<repo>/eventbuddy:<tag>` (`docker login` via `cr.sh credentials docker-login`).
3. **Create the runtime** — PUBLIC mode, flavor e.g. `1x1-general`, with `--env-file` (`MICROSOFT_APP_ID`, `GRAPH_TENANT_ID`, `AGENTBASE_LLM_*`, `DATABASE_URL`, `REDIS_URL`, …) and `--from-cr` for image auth. This auto-creates a `DEFAULT` endpoint.
4. **Get the DEFAULT endpoint URL** from the create response.
5. **Wire Microsoft:** set the Azure Bot *Messaging endpoint* = `<endpoint>/api/messages`; set the Graph subscription `notificationUrl` = `<endpoint>/api/webhooks/graph`; upload the Teams app manifest.
6. **Migrations:** run `alembic upgrade head` against the target Postgres before serving traffic.
7. **Test** in Teams → message the bot → Azure Bot Service → AgentBase endpoint → response.

### 15.6 Data stores & network mode

AgentBase hosts the **runtime only** — **Postgres, Redis, and pgvector are not part of it**. Point `DATABASE_URL`/`REDIS_URL` at managed instances (VNG Cloud DB/Redis). If those sit in a private VPC, switch the runtime to **VPC network mode** (`--network-mode VPC` + `--vpc-id`/`--subnet-id`, and a `-vpc` flavor) so the container can reach them privately. **PUBLIC mode + a publicly reachable DB is the simpler hackathon path.**

### 15.7 Scaling & updates

- The API is stateless (session lives in Redis) → scale horizontally via `--min/--max-replicas`.
- Each `runtime.sh update` creates a new **version**; the `DEFAULT` endpoint auto-tracks it. Roll back by updating to the previous image, or canary-test via a custom endpoint first.
- **Resource Gateway:** configured separately; tool targets + Policy Groups registered once and pointed at the runtime.

---

## 16. Observability

- **Logging:** structured JSON logs (request id, `event_id`, `teams_user_id`, tool name) via `common/logging.py`; shipped to **AgentBase Monitor**.
- **Metrics:** per-capability counters (events created, reminders sent, reports generated), LLM token usage, job success/failure, webhook lag.
- **Audit:** `audit_log` is the authoritative record of every HITL-confirmed action.
- **Tracing:** correlate a Teams turn → agent tool calls → Graph calls by a single request id.

---

## 17. Testing Strategy

| Level | What | How |
|-------|------|-----|
| **Unit** | Domain services, parsers, prompt builders, session/context logic | pytest, no I/O; LLM and Graph mocked |
| **Integration** | Repositories vs Postgres, ingestion pipeline, Graph client | testcontainers (Postgres/Redis), recorded Graph responses |
| **E2E** | Full turn: inbound activity → response | Bot Framework `TestAdapter`; assert cards/text & DB side-effects |
| **Contract** | Tool input/output schemas, Policy rules | schema validation + Policy simulation |

Follow TDD for domain logic (the highest-value, most testable code). LLM-dependent steps are tested by asserting on the *structured* output contract (JSON shape), with the model mocked; a small suite of live "golden" prompts runs separately.

---

## 18. Build Phasing / Roadmap

Designed so the hackathon-critical slice ships first, on the full architecture.

**Phase 0 — Foundation (Day 1–2)**
AgentBase runtime + registry, FastAPI skeleton, Bot Framework echo, Graph auth via Identity, Postgres + Alembic + base tables, Redis. *Milestone: bot replies in Teams; auth works.*

**Phase 1 — Lifecycle core (Day 2–5) [hackathon-critical]**
Event creation + channel provisioning, Broadcast (Outlook+Teams), Registration distributor + calendar invite, Smart Reminder + escalation, Feedback collector. *Milestone: one-prompt flow runs broadcast → reminder live.*

**Phase 1.5 — Auto Report + Suggestions (Day 5–6) [the differentiator]**
Feedback sentiment/themes, metrics aggregation, Qwen summary + suggestions, report card + draft email. *Milestone: end-to-end demo (broadcast + reminder + report).*

**Phase 1.6 — Document ingestion (pulled into hackathon scope)**
> Originally Phase 2; **pulled forward** because the flagship demo ("read the uploaded participant list + guide, then email everyone the doc link") depends on it. See `__plans__/04-amendments.md`.
Graph file webhook → download → parse (xlsx/docx/pdf) → LLM-structure → upsert `documents` + extracted members/tasks → proactive HITL card → bulk send. *Milestone: upload a participant xlsx in the channel → agent offers to email the roster a guide link → one click sends.*

**Phase 2 — Remaining proactive intelligence (post-hackathon)**
pgvector RAG over docs + chat, brainstorm synthesis, full personal-scope memory, cross-event learning, passive channel-history awareness (RSC `getAllMessages`).

**Phase 3 — Hardening**
Resource Gateway + Policy rollout, full audit, subscription renewal robustness, observability dashboards, scale testing.

---

## 19. Appendix

### 19.1 Document-structuring system prompt (ingestion)
```
You are a professional event-data analysis assistant. Read the raw text/table
content from an organizer's document and extract structured information.
- If it contains a task list, output a JSON array of objects:
  {"task_name": string, "assignee_email": string, "due_date": "YYYY-MM-DD"}.
- If it contains a participant list, extract a JSON array of {name, email}.
- Return ONLY raw JSON. No explanatory text outside the JSON.
```

### 19.2 HTTP endpoints
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/messages` | Bot Framework activities (Teams) |
| POST | `/api/webhooks/graph` | Graph change notifications (file events) |
| GET | `/api/health` | liveness/readiness |

### 19.3 Event lifecycle states
`ideation → planning → running → wrap_up` — transitions are driven by EO commands, document ingestion, and the scheduler (e.g. `start_at` → `running`, `end_at` → `wrap_up`).

### 19.4 Model assignment
| Task | Model |
|------|-------|
| Intent classification, document extraction, chat | Gemma-4-31b-it |
| Feedback summarization, report suggestions | Qwen-3-27B |
| Embeddings (RAG) | MaaS embedding model |

### 19.5 Minimal `Dockerfile` (satisfies the port-8080 / `/health` contract)

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# System deps for document parsing (pdf/docx) if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./

EXPOSE 8080

# uvicorn serves the FastAPI app; the in-process scheduler starts in the app lifespan.
CMD ["uvicorn", "eventbuddy.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

> Build for the platform AgentBase runs on: `docker build --platform linux/amd64 -t vcr.vngcloud.vn/<repo>/eventbuddy:<tag> .`

### 19.6 Minimal `src/eventbuddy/main.py` (FastAPI + Bot Framework + health)

This is the entrypoint that bridges AgentBase's HTTP contract to the Bot Framework. It listens on 8080, exposes `/health`, accepts Teams activities on `/api/messages`, accepts Graph notifications on `/api/webhooks/graph`, and starts the in-process scheduler in the app lifespan.

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from botbuilder.core import CloudAdapter, ConfigurationBotFrameworkAuthentication
from botbuilder.schema import Activity

from eventbuddy.config import settings
from eventbuddy.bot.activity_router import EventBuddyBot
from eventbuddy.scheduler.triggers import start_scheduler, shutdown_scheduler

# Bot Framework adapter — validates inbound JWT using MICROSOFT_APP_ID/PASSWORD,
# and is also used to send outbound (proactive) messages back to the Bot Connector.
adapter = CloudAdapter(ConfigurationBotFrameworkAuthentication(settings.bot_auth))
bot = EventBuddyBot()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the in-process reminder/escalation/report scheduler on boot.
    scheduler = start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler(scheduler)


app = FastAPI(title="EventBuddy", lifespan=lifespan)


@app.get("/health")          # AgentBase marks the runtime ACTIVE when this returns 200.
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/messages")   # Teams -> Azure Bot Service -> here.
async def messages(req: Request) -> Response:
    body = await req.json()
    activity = Activity().deserialize(body)
    auth_header = req.headers.get("Authorization", "")
    # process_activity validates the JWT and invokes the bot's turn handler.
    # The bot replies by calling back out to serviceUrl (async), not via this response.
    await adapter.process_activity(auth_header, activity, bot.on_turn)
    return Response(status_code=200)   # immediate ack


@app.post("/api/webhooks/graph")   # SharePoint/OneDrive FileCreated notifications.
async def graph_webhook(req: Request) -> Response:
    # Graph subscription validation handshake.
    token = req.query_params.get("validationToken")
    if token:
        return Response(content=token, media_type="text/plain", status_code=200)

    payload = await req.json()
    # Enqueue ingestion jobs (dedup via Redis); return fast so Graph doesn't retry.
    await bot.handle_graph_notifications(payload)
    return Response(status_code=202)
```

> Notes: only `/health` + port 8080 are required by AgentBase; the bot/webhook routes are EventBuddy's own. The bot's actual logic (intent routing, gatekeeper, LangGraph) lives in `bot/activity_router.py` → `agent/`. Outbound replies and proactive reminders use the same `adapter` with a stored `conversationReference`.
```

