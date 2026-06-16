# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

EventBuddy is a Microsoft Teams bot that manages the event lifecycle (create event, focus on an event, remind members, list tasks, generate reports). It runs as a FastAPI app deployed on **GreenNode AgentBase**, backed by Postgres (Supabase) and Redis, and talks to an OpenAI-compatible **MaaS** endpoint for the LLM. The conversational brain is a LangGraph `create_react_agent` tool-calling loop with a three-layer memory stack (Phase 1.7).

## Commands

Run from the repo root (targets forward to `deployment/Makefile`, which uses `venv/`):

- `make test` — unit tests (`pytest -q`; `addopts = -m 'not integration'` so integration tests are skipped by default)
- `make lint` — `ruff check src/ tests/`
- `make run` — uvicorn on `:8080`
- Single test: `venv/bin/python -m pytest tests/unit/test_runner.py::test_name -q`
- Integration tests (need live Postgres/Redis): `venv/bin/python -m pytest -m integration` — bring up datastores with `docker compose -f deployment/docker-compose.yml up -d db redis` first
- Live LLM smoke tests are creds-gated and skip without MaaS credentials in `.env`

Deploy (wraps the bundled AgentBase skill scripts in `.claude/skills/agentbase/scripts`):

- `make creds` — store GreenNode IAM client_id/secret in `.greennode.json` (interactive)
- `make deploy` — build, push, create/update the runtime, health-check
- `make status` / `make endpoint` / `make health` / `make logs` / `make destroy`
- Override deploy config inline, e.g. `make deploy FLAVOR=2x4-general RUNTIME_NAME=EventBuddy`

DB migrations: `venv/bin/alembic upgrade head`. The container entrypoint runs this on boot (best-effort — a DB hiccup won't stop the app serving).

## Architecture

**Request flow.** Teams → `POST /api/messages` ([api/messages.py](src/eventbuddy/api/messages.py)) → Bot Framework `CloudAdapter` → `EventBuddyBot` ([bot/activity_router.py](src/eventbuddy/bot/activity_router.py)) → a thin LangGraph wrapper ([agent/graph.py](src/eventbuddy/agent/graph.py), one `orchestrate` node) → `Orchestrator.handle(...)`. There is also a dev-only `POST /api/dev/handle` ([api/dev.py](src/eventbuddy/api/dev.py)) that bypasses Bot Framework auth (mounted only when `DEV_ROUTES_ENABLED=true`) — DM-scoped, multi-turn, with `reset: true` support.

**The Orchestrator is the routing seam** ([agent/orchestrator.py](src/eventbuddy/agent/orchestrator.py)). When `agent_mode="llm"` and a runner is wired, it calls the LLM tool-calling runner; on any exception, or when `agent_mode="regex"`, or when MaaS creds are absent, it **degrades to the deterministic Phase 1 regex router** (`_regex_handle`). The `handle(...)` signature is stable so callers never change. This graceful-degradation pattern is load-bearing — keep both paths working.

**Wiring** ([agent/wiring.py](src/eventbuddy/agent/wiring.py)) is the composition root. It defines the capability closures (`provision_fn`, `resolve_event_fn`, `remind_fn`, `report_fn`, `query_tasks_fn`) **once**, then shares them between the regex router and the LLM tool bodies (DRY). `build_orchestrator()` decides regex-vs-LLM based on creds + `agent_mode`.

**The agent runner** ([agent/runner.py](src/eventbuddy/agent/runner.py)) wraps `create_react_agent` (Path A, spike-selected 2026-06-12). Model + checkpointer are shared singletons; tools and prompt are rebuilt per request to bind the caller's `RequestContext`. A `pre_model_hook` trims the working window to ≤4096 tokens, cutting **only** on human/assistant boundaries (`start_on="human"`) so a `tool_call_id` is never orphaned (orphaning breaks the MaaS API).

**Tools** ([agent/tools.py](src/eventbuddy/agent/tools.py)) — each tool's docstring is the model-facing description. **Critical security invariant (cross-cutting rule 2):** identity, role, scope, and focused-event come from the server-built `RequestContext` ([agent/context.py](src/eventbuddy/agent/context.py)) captured in the factory closure — they are **never** tool arguments, so the model cannot spoof who the caller is or what they're allowed to do. Role gating uses `ROLE_RANK` from [bot/auth.py](src/eventbuddy/bot/auth.py) (`member` < `moderator` < `host`). Role is **scope-dependent** (resolved once in `_default_role` + the wiring `role_resolver`, then read everywhere): a 1-1 DM caller is `host`; a **group chat is a flat peer space** — every participant is `moderator` regardless of membership, so anyone can run privileged actions (outbound sends still gated by the HITL confirm card); a channel uses the caller's real `EventMember.role`. See the security section of [documents/System-Architecture.md](documents/System-Architecture.md) (detailed dev rationale lives in `__documents__/`, gitignored).

**Three-layer memory** (all keyed by the scope-aware `thread_id`: `event:{channel_id}` for shared channels, `dm:{user_id}` for 1-1 DMs — see `RequestContext.thread_id`):
1. **Working window** — LangGraph Redis checkpointer, 24h TTL ([agent/memory.py](src/eventbuddy/agent/memory.py)). Degrades to `InMemorySaver` without Redis. `session_lock` serializes concurrent posts to a shared `event:` thread.
2. **Durable transcript** — Postgres `conversation_messages` ([agent/transcript.py](src/eventbuddy/agent/transcript.py)). Persists **user/assistant turns only** — tool-call/result messages are dropped. Idempotent flush via a per-thread high-water mark; rehydrates an empty window from the most-recent turns within budget.
3. **Rolling summary** — Postgres `session_summaries` ([agent/summarizer.py](src/eventbuddy/agent/summarizer.py)). A compact running gist of everything older than the rehydration tail, refreshed **out of band** by an APScheduler job ([scheduler/](src/eventbuddy/scheduler/)) — no per-turn latency. `covered_through` is the watermark. Uses `LLMGateway.summarize` (a non-chat LLM call, not the ReAct loop).

When the runner finds the Redis window empty, it seeds initial state from the summary + transcript tail (`_seed_messages` / `_window_empty` in runner.py).

**Data layer.** SQLAlchemy 2.0 ORM in [domain/models.py](src/eventbuddy/domain/models.py); repositories in [data/repositories/](src/eventbuddy/data/repositories/). Use the `session_scope()` context manager ([data/db.py](src/eventbuddy/data/db.py)) — it commits on success, rolls back on exception. Migrations in [alembic/versions/](alembic/versions/); `alembic/env.py` injects `settings.database_url` and imports the models so autogenerate sees them.

## Conventions & gotchas

- **MaaS model IDs are namespaced** — bare `gemma-4-31b-it` / `qwen-3-27b` return 404. Use the namespaced form (e.g. `qwen/qwen3-5-27b`, verified 2026-06-12). Chat brain must emit clean OpenAI `tool_calls`. See [config.py](src/eventbuddy/config.py).
- **Everything degrades gracefully** — no MaaS creds → regex router; no Redis → in-memory checkpointer; no Graph creds → create-event persists locally only; DB unreachable on boot → app still serves, memory features degrade. Preserve this when editing; don't introduce hard failures on missing creds.
- Config is `pydantic-settings` from `.env` (`extra="ignore"`). See [.env.example](.env.example) for the full key list.
- Python 3.12, `src/` layout, package `eventbuddy`. Ruff: line-length 100, rules `E,F,I,UP,B`.
- Datastores (Supabase Postgres, managed Redis) and MaaS are reached **directly over public TLS** — no overlay network / Tailscale.
- Phase plans live in [__plans__/](__plans__/) and [phases/](phases/); the system architecture doc is [documents/System-Architecture.md](documents/System-Architecture.md). Dev-only scratch docs (IT onboarding, emulator/test guides, memory deep-dives) live in `__documents__/` (gitignored).
