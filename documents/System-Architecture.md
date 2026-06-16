# EventBuddy — System Architecture

🌐 **English** · [Tiếng Việt](System-Architecture.vi.md)

> A Microsoft Teams bot that runs the whole event lifecycle — create → focus → remind → report —
> through one conversational agent. This document explains how it's built.

**Audience:** engineers and reviewers who want to understand how EventBuddy works.
**Companion docs:** [Teams Setup Guide](Teams-Setup-Guide.md) · [README](../README.md)

---

## 1. What it is, in one paragraph

EventBuddy is an **event-centric AI assistant** for the people who run internal events
(Event Organizers, Employee Engagement, L&D). It lives inside Microsoft Teams as a bot. An
organizer talks to it the way they'd talk to a capable teammate — *"this group is for the Spring
Hackathon, help us organize"*, *"add a task to send thank-you emails, due June 20"*, *"remind
everyone who hasn't registered yet"*, *"write the post-event report"* — and the agent drives the
work: provisioning a per-event workspace, reading planning files, sending personalized
omnichannel reminders, and generating a report with suggestions for next time.

It is built so that **every external dependency degrades gracefully**: no LLM credentials → a
deterministic regex router still answers; no Redis → in-memory conversation state; no Microsoft
Graph → event data persists locally. The bot never hard-fails because one integration is missing.

---

## 2. The painpoint it removes

Running one internal event is a fixed, repetitive lifecycle that costs an organizer **4–6 hours of
manual overhead, every time**:

```
announce → distribute registration → chase registrations → remind before D-day
        → collect feedback → write the post-event report
```

Every step is manual coordination: copy-pasting member lists, chasing non-responders one by one,
re-typing the same reminder across email and chat, and assembling a report by hand. Organizers
typically run **2–3 events at once**, so the overhead multiplies and the contexts bleed together.

EventBuddy collapses that into a single conversational surface. Describe the event once; the agent
keeps each event's context isolated (`event_id` partitions everything) and does the repetitive work.

---

## 3. High-level architecture

Three ingress paths feed one bot core. The core runs a tool-calling LLM agent that acts through a
typed, permission-gated tool layer onto Microsoft 365 and the data stores.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          MICROSOFT TEAMS CLIENTS                               │
│     1-1 DM (personal)        Group chat        Team channel        Outlook     │
└───────────┬───────────────────────┬───────────────────┬──────────────┬────────┘
            │  Bot Framework activities (via Azure Bot Service)         │ Graph
            ▼                                                           ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  INGRESS (FastAPI)   /api/messages   /api/webhooks/graph   /api/forms   /health │
│                      + landing page at  /   + dev-only  /api/dev/handle          │
└───────────────────────────────┬────────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  BOT GATEWAY        CloudAdapter (JWT validation) · EventBuddyBot ·             │
│                     scope + role resolution · HITL confirm cards                 │
└───────────────────────────────┬────────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  AGENT (LangGraph create_react_agent)                                           │
│  Orchestrator (routing seam) → LLM tool loop  ──or──  regex router (fallback)    │
│  three-layer memory: Redis window → Postgres transcript → rolling summary        │
└───────────────────────────────┬────────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  TOOL LAYER (per-request, context-bound)                                        │
│  create_event · setup_event · create_task · update_task · prepare_reminders ·    │
│  send_outlook_mail · send_teams_message · read_event_file · generate_report · …  │
└───────────────────────────────┬────────────────────────────────────────────────┘
            ┌────────────────────┼─────────────────────┬─────────────────────┐
            ▼                    ▼                     ▼                     ▼
┌────────────────┐   ┌────────────────────┐  ┌──────────────────┐  ┌────────────────┐
│  CAPABILITIES  │   │  SCHEDULER         │  │  DATA LAYER       │  │  INTEGRATIONS   │
│ provisioning · │   │ APScheduler:       │  │ Postgres (ORM) ·  │  │ MS Graph ·      │
│ reminders ·    │   │ rolling-summary    │  │ Redis (window +   │  │ MaaS LLM ·      │
│ reporting ·    │   │ refresh job        │  │ sessions)         │  │ Tavily web      │
│ ingestion · …  │   │                    │  │                   │  │ (optional)      │
└────────────────┘   └────────────────────┘  └──────────────────┘  └────────────────┘
```

**Why this shape.** Uploads, reminders, and replies all happen asynchronously, so the agent's
request path stays decoupled from time-based work (the scheduler) and from outbound delivery
(replies are *outbound* calls back to Microsoft, not the HTTP response). Layering keeps each
concern independently testable and lets the agent reason over a small, well-bounded tool surface.

---

## 4. The request flow

A message from Teams travels a fixed path; the same `handle(...)` seam serves every scope.

```
Teams → Azure Bot Service → POST /api/messages  (api/messages.py)
      → CloudAdapter (validates Bot Framework JWT)  (bot/adapter.py)
      → EventBuddyBot  (bot/activity_router.py)      — resolves scope, identity, focused event
      → LangGraph wrapper, one `orchestrate` node    (agent/graph.py)
      → Orchestrator.handle(...)                      (agent/orchestrator.py)  ← the routing seam
          ├─ agent_mode="llm" + creds present → LLM tool-calling runner (agent/runner.py)
          └─ on any exception / agent_mode="regex" / no creds → deterministic regex router
```

Bot Framework is **not** request/response. `POST /api/messages` returns `200 OK` as an *ack*; the
actual reply is an **outbound call** from the container back to the Bot Connector at the activity's
`serviceUrl`. Proactive messages (scheduled reminders, escalations) reuse that same outbound path
via a stored conversation reference — which is why the scheduler can message people with no
inbound trigger.

There is also a dev-only `POST /api/dev/handle` (mounted only when `DEV_ROUTES_ENABLED=true`) that
bypasses Bot Framework auth for local, multi-turn testing.

---

## 5. The Orchestrator — graceful degradation as a design principle

The **Orchestrator** ([`agent/orchestrator.py`](../src/eventbuddy/agent/orchestrator.py)) is the
single routing seam. Its `handle(...)` signature is stable so callers never change. Inside:

- When `agent_mode="llm"` and an LLM runner is wired, it calls the tool-calling runner.
- On **any** exception, or when `agent_mode="regex"`, or when LLM credentials are absent, it
  **degrades to a deterministic regex router** that still handles the core verbs.

This is load-bearing, not a nicety. The whole system is built to degrade rather than fail:

| Missing dependency | Behavior |
|---|---|
| MaaS / LLM credentials | Falls back to the regex router |
| Redis | Conversation window uses an in-memory checkpointer |
| Microsoft Graph credentials | `create_event` persists locally; channel/file/mail features report unavailable |
| Database on boot | App still serves; memory features degrade |

**Wiring** ([`agent/wiring.py`](../src/eventbuddy/agent/wiring.py)) is the composition root. It
defines the capability closures (`provision_fn`, `remind_fn`, `report_fn`, …) **once** and shares
them between the regex router and the LLM tool bodies (DRY), then `build_orchestrator()` picks
regex-vs-LLM from the available credentials and `agent_mode`.

---

## 6. The agent runner

The runner ([`agent/runner.py`](../src/eventbuddy/agent/runner.py)) wraps LangGraph's
`create_react_agent` tool-calling loop.

- The **model and checkpointer are shared singletons**; **tools and the system prompt are rebuilt
  per request** so they bind the caller's `RequestContext` (see §8).
- A `pre_model_hook` **trims the working window to ≤4096 tokens**, cutting only on human/assistant
  boundaries (`start_on="human"`) so a `tool_call_id` is never orphaned — orphaning breaks the
  LLM API.
- When the Redis window is empty, the runner **seeds initial state from the rolling summary +
  transcript tail** so a conversation resumes with context after the window expires.
- Every tool call this turn is recorded into a request-scoped trace; failures are classified
  (model-fault → retry; system-fault → a clean user message), and an optional debug footer can
  surface what the agent did.

---

## 7. Three-layer memory

All three layers are keyed by a scope-aware `thread_id`: `event:{channel_id}` for shared channels,
`dm:{user_id}` for 1-1 DMs.

1. **Working window** — a LangGraph Redis checkpointer with a 24h TTL
   ([`agent/memory.py`](../src/eventbuddy/agent/memory.py)). Degrades to `InMemorySaver` without
   Redis. A `session_lock` serializes concurrent posts to a shared `event:` thread.
2. **Durable transcript** — Postgres `conversation_messages`
   ([`agent/transcript.py`](../src/eventbuddy/agent/transcript.py)). Persists **user/assistant
   turns only** (tool-call/result messages are dropped). Idempotent flush via a per-thread
   high-water mark; rehydrates an empty window from the most-recent turns within budget.
3. **Rolling summary** — Postgres `session_summaries`
   ([`agent/summarizer.py`](../src/eventbuddy/agent/summarizer.py)). A compact running gist of
   everything older than the rehydration tail, refreshed **out of band** by an APScheduler job
   (no per-turn latency). `covered_through` is the watermark.

This stack lets a conversation stay coherent far past the 4096-token window without re-sending the
whole history to the model on every turn.

---

## 8. Identity, scope, and the security invariant

**The model can never spoof who the caller is.** Identity, role, scope, and the focused event come
from a **server-built `RequestContext`** ([`agent/context.py`](../src/eventbuddy/agent/context.py))
that is captured in the per-request tool factory closure — they are **never tool arguments**. The
model decides *what* action to take; it cannot decide *who it is acting as*.

Role is **scope-dependent**, resolved once and read everywhere:

| Scope | Resolved role | Why |
|---|---|---|
| **1-1 DM** (`personal`) | `host` | The user is the event leader, acting privately. |
| **Group chat** (`group`) | `moderator` (everyone) | A group chat is a flat, invite-only peer space — any participant may run any action. |
| **Team channel** (`channel`) | the caller's real `EventMember.role` (default `member`) | Team-backed; org roles are meaningful and membership is the source of truth. |

Role gating uses `ROLE_RANK` from [`bot/auth.py`](../src/eventbuddy/bot/auth.py)
(`member < moderator < host`). Two further guards protect outbound side-effects:

- **HITL confirmation cards** — every outbound action (mail, Teams messages, reminders) requires an
  explicit Adaptive-Card confirmation; nothing sends silently. The card re-resolves the caller's
  role at click time, so authorization stays consistent.
- **Prompt-injection framing** — external/untrusted text (channel messages, fetched web pages, file
  contents) is wrapped in an `external_untrusted_content` envelope before it reaches the model, so
  it is treated as reference data, never as instructions.

---

## 9. Capabilities (the agent's tool surface)

Capabilities live in [`capabilities/`](../src/eventbuddy/capabilities/) and are exposed to the LLM
as typed tools in [`agent/tools.py`](../src/eventbuddy/agent/tools.py). Each tool's docstring is its
model-facing description. The current surface:

| Group | Tools | Notes |
|---|---|---|
| **Event setup** | `create_event`, `setup_event`, `set_focus_event`, `list_my_events`, `sync_event_members` | Provision from a DM, or bind a group/channel to an event and enroll members by corporate identity. |
| **Tasks** | `create_task`, `update_task`, `list_my_tasks`, `list_event_tasks` | Conversational task board; any member may create/update their own, moderators/hosts any. |
| **Reminders & messaging** | `prepare_reminders`, `send_outlook_mail`, `send_email`, `send_teams_message`, `send_participant_reminders` | All HITL-gated. `send_teams_message` supports per-recipient personalization with merge/separate confirmation cards. |
| **Files & intelligence** | `list_event_files`, `read_event_file`, `read_participant_file`, `ingest_event_files`, `read_channel_discussion` | Describe→match→read over chat/channel files; xlsx/docx/pdf/csv via parsers, images/scans via a vision model. |
| **Members & context** | `list_members`, `get_event_context` | Scope-aware roster; cross-context event snapshot. |
| **Feedback & reporting** | `set_feedback_sources`, `generate_report` | Wire a Form + its responses workbook; generate an AI post-event report. |
| **Web (optional)** | `web_search`, `web_fetch` | Registered only when Tavily is configured — the agent never advertises a capability the deployment can't fulfil. |

---

## 10. Data layer

SQLAlchemy 2.0 ORM in [`domain/models.py`](../src/eventbuddy/domain/models.py); repositories in
[`data/repositories/`](../src/eventbuddy/data/repositories/). All writes go through the
`session_scope()` context manager ([`data/db.py`](../src/eventbuddy/data/db.py)) — commit on
success, rollback on exception.

- **Postgres** (Supabase) — events, members, tasks, reports, feedback, chat-file catalog,
  scheduled jobs, audit log, and the durable transcript + rolling summary tables.
- **Redis** — the LangGraph working-window checkpointer (24h TTL) and session/turn state.

Migrations live in [`alembic/versions/`](../alembic/); `alembic/env.py` injects the database URL
and imports the models so autogenerate sees them. The container entrypoint runs
`alembic upgrade head` on boot, best-effort — a DB hiccup won't stop the app from serving.

---

## 11. Scheduling & background work

An in-process APScheduler ([`scheduler/`](../src/eventbuddy/scheduler/)) runs in the FastAPI
lifespan. Its main job today refreshes the **rolling summary** out of band, so summarization never
adds latency to a user turn. The same outbound-reply mechanism (a stored conversation reference)
lets scheduled work deliver proactive reminders with no inbound trigger.

---

## 12. External integrations

- **Microsoft Graph** — channel creation, channel message read/send, SharePoint/OneDrive file
  access, and Outlook mail. Used only by proactive/channel/file/mail features; the conversational
  reply path needs **no** Graph permissions. The project's tenant integration uses delegated Graph
  auth behind a sign-in-card OAuth flow.
- **MaaS (Model-as-a-Service)** — an OpenAI-compatible LLM endpoint (GreenNode). Model IDs are
  **namespaced** (e.g. `qwen/qwen3-5-27b`); bare IDs 404. The chat brain must emit clean OpenAI
  `tool_calls`.
- **Tavily** (optional) — web search/fetch for brainstorming and external facts.

---

## 13. Deployment

EventBuddy is a **Custom Agent** on **GreenNode AgentBase** — a generic container host. The
platform contract is minimal: the container **listens on port 8080** and exposes **`GET /health`**
returning 200 when ready. Everything else (the routes) is ours.

```
Teams client → Azure Bot Service (Bot Connector) → AgentBase public endpoint → container :8080
```

Two registrations live **outside** AgentBase, in the Microsoft tenant: an **Azure Bot resource**
(whose messaging endpoint is `https://<agentbase-endpoint>/api/messages`) and the **Teams app
manifest** (the uploaded package). The AgentBase endpoint URL is the glue — it is both the bot's
messaging endpoint and the Graph webhook URL. Datastores (Supabase Postgres, managed Redis) are
**not** part of the runtime; they're reached directly over public TLS.

The API is stateless (session lives in Redis), so it scales horizontally. The deploy flow is
wrapped in `make deploy` (build → push to the managed registry → create/update runtime →
health-check). See the [README](../README.md#local-development) for commands and the
[Teams Setup Guide](Teams-Setup-Guide.md) for the Microsoft-side wiring.

---

## 14. Codebase map

```
src/eventbuddy/
├── main.py                 # FastAPI app factory + lifespan (starts the scheduler)
├── config.py               # pydantic-settings, env-driven
├── api/                    # HTTP surface: messages, webhooks, forms, health, landing, dev
├── bot/                    # Bot Framework adapter, activity router, auth/roles, HITL confirm cards
├── agent/                  # the brain: orchestrator, runner, tools, wiring, 3-layer memory, prompts
├── capabilities/           # one module per lifecycle feature (provisioning, reminders, reporting, …)
├── domain/                 # SQLAlchemy models + domain logic (events, members, tasks, reports)
├── data/                   # db engine/session, redis, repositories
├── ingestion/              # file parse → LLM structure → upsert pipeline
├── integrations/           # the only place that talks to external systems (Graph, LLM, web)
├── scheduler/              # APScheduler jobs (rolling-summary refresh) + triggers
└── common/                 # logging, errors, ids
```

**Boundaries:** `api/` and `bot/` know nothing about SQL; `domain/` knows nothing about Bot
Framework; `integrations/` is the only layer that talks to external systems; `agent/wiring.py` is
the seam where everything is composed. That separation is what makes graceful degradation possible —
a missing integration disables one capability instead of breaking the bot.
