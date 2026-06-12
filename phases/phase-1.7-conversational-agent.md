# Phase 1.7 — Conversational Tool-Calling Agent (implemented)

Status: **complete** on branch `phase-1-lifecycle-core`. 96 unit tests green, `ruff check .` clean. Live LLM smoke + transcript repo tests are `integration`-marked (skip without MaaS creds / local Postgres+Redis).

The agent brain moves from a deterministic regex command-router to an **LLM-driven conversational agent that calls the event capabilities as tools** (LangGraph `create_react_agent`, Path A — native tool calling, model `qwen/qwen3-5-27b`, spike recorded in [__plans__/04-amendments.md](__plans__/04-amendments.md)). Identity, permissions and persistence stay **server-authoritative**; the model only decides *what* to do and extracts the args. The regex router is the graceful fallback.

## Request path
DM: [api/dev.py](src/eventbuddy/api/dev.py) (DM-scoped, multi-turn, `reset`) and Teams: [bot/activity_router.py](src/eventbuddy/bot/activity_router.py) → [agent/orchestrator.py](src/eventbuddy/agent/orchestrator.py) → `runner.run(text, ctx)` → ReAct loop → tool → grounded reply. On LLM error / `agent_mode=regex` → Phase 1 [agent/intents.py](src/eventbuddy/agent/intents.py).

## What's new

| Piece | What it does | File |
|---|---|---|
| Chat model factory | `ChatOpenAI` pointed at MaaS (supports `bind_tools`) | [agent/model.py](src/eventbuddy/agent/model.py) |
| Request context | Server-built identity/role/scope + scope-aware `thread_id`, speaker tagging | [agent/context.py](src/eventbuddy/agent/context.py) |
| Tool registry | `@tool` wrappers over the Phase 1 capability closures; identity injected via closure (not model args) | [agent/tools.py](src/eventbuddy/agent/tools.py) |
| Permission gate | `Gatekeeper`/role check **inside** mutating tools (`create_event`, `prepare_reminders`) | [agent/tools.py](src/eventbuddy/agent/tools.py), [bot/auth.py](src/eventbuddy/bot/auth.py) |
| System prompt | Persona; chat normally, tool only on intent, ground in results, ask when ambiguous | [agent/prompts/system.py](src/eventbuddy/agent/prompts/system.py) |
| Agent runner | `create_react_agent` behind a factory; A/B isolation; ≤4096-tok tool-pair-aware trimmer | [agent/runner.py](src/eventbuddy/agent/runner.py) |
| Working window | Redis checkpointer (24h TTL) + per-thread lock; InMemory/no-op fallback | [agent/memory.py](src/eventbuddy/agent/memory.py) |
| Durable transcript | Postgres `conversation_messages` (user/assistant only); idempotent flush + budgeted rehydrate | [agent/transcript.py](src/eventbuddy/agent/transcript.py) |
| Rolling summary | Postgres `session_summaries`; folds older turns; background APScheduler job | [agent/summarizer.py](src/eventbuddy/agent/summarizer.py), [scheduler/jobs.py](src/eventbuddy/scheduler/jobs.py) |
| Orchestrator entry | Conversational route + regex fallback + `reset_dm`; stable `handle()` signature | [agent/orchestrator.py](src/eventbuddy/agent/orchestrator.py) |
| Wiring + config | Composes runner/summarizer; degrades without creds; `AGENT_MODE` | [agent/wiring.py](src/eventbuddy/agent/wiring.py), [config.py](src/eventbuddy/config.py) |

## Layered memory (session-scoped)
`thread_id` = `event:{channel_id}` (shared channel/event) | `dm:{user_id}` (private 1-1). Write/read top→bottom:
1. **Redis working window** — LangGraph checkpointer, live graph with tool-call/result pairs intact, trimmed to ≤4096 tok on user/assistant boundaries, 24h TTL.
2. **Postgres `conversation_messages`** — durable user/assistant transcript (tool noise dropped); overflow + rehydration source (Redis-first → Postgres tail).
3. **Postgres `session_summaries`** — rolling per-session summary of older turns, refreshed off the request path, prepended when seeding an empty window.

Migration: [alembic/versions/0002_conversation_memory.py](alembic/versions/0002_conversation_memory.py).

## Notes / not in this phase
- The chat path now **requires** `AGENTBASE_LLM_BASE_URL` + `AGENTBASE_LLM_API_KEY`; without them it auto-degrades to the regex router (still boots and serves).
- Channel threads key on `channel_id` (`event:{channel_id}`) until the Phase 1.6 channel→event binding lands; DM is the primary surface and the dev route is DM-scoped.
- `create_react_agent` is used per the plan; it is deprecated in LangGraph v1 in favour of `langchain.agents.create_agent` (functional through v1, a future migration).
- Run `alembic upgrade head` before the live path so `conversation_messages`/`session_summaries` exist; otherwise the runner errors and falls back to regex (verified behaviour).
