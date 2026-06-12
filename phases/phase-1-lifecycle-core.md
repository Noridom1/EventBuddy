# Phase 1 — Lifecycle Core (implemented)

Status: **complete** on branch `phase-1-lifecycle-core`. 45 unit + 3 integration tests green, `ruff check .` clean.

A Teams message is classified → routed to a capability → reply composed; events + rosters persist; time-based reminder/feedback jobs schedule in-process. Live Teams/Graph sends are mock-tested and activate once Microsoft creds land.

## Request path
[api/messages.py](src/eventbuddy/api/messages.py) → [bot/activity_router.py](src/eventbuddy/bot/activity_router.py) → LangGraph wrapper [agent/graph.py](src/eventbuddy/agent/graph.py) → [agent/orchestrator.py](src/eventbuddy/agent/orchestrator.py) → a capability. Health/boot: [main.py](src/eventbuddy/main.py) (lifespan starts the scheduler), [api/health.py](src/eventbuddy/api/health.py).

## Capabilities

| Capability | What it does | File |
|---|---|---|
| Intent routing | Rule-based classify of `CREATE_EVENT / CONTEXT_SWITCH / REMIND / QUERY_TASKS / GENERATE_REPORT / SMALL_TALK` | [agent/intents.py](src/eventbuddy/agent/intents.py) |
| Orchestration | Maps intent → capability fn, composes reply | [agent/orchestrator.py](src/eventbuddy/agent/orchestrator.py), wired in [agent/wiring.py](src/eventbuddy/agent/wiring.py) |
| Provisioning | Create event + Teams channel + member roster (host/member) | [capabilities/provisioning.py](src/eventbuddy/capabilities/provisioning.py) |
| Broadcast | LLM-composed announcement to channel + email | [capabilities/broadcast.py](src/eventbuddy/capabilities/broadcast.py) |
| Registration | Email the registration link to members | [capabilities/registration.py](src/eventbuddy/capabilities/registration.py) |
| Reminders | Personalized Teams DM or formal Outlook mail | [capabilities/reminders.py](src/eventbuddy/capabilities/reminders.py) |
| Feedback dispatch | Email the feedback-form link (analysis = Phase 1.5) | [capabilities/feedback.py](src/eventbuddy/capabilities/feedback.py) |
| Context switching | Per-user "focused event" in Redis | [agent/session.py](src/eventbuddy/agent/session.py) |
| Authorization | Membership + role-rank gatekeeper (`member<moderator<host`) | [bot/auth.py](src/eventbuddy/bot/auth.py) |
| Scheduling | APScheduler jobs: D-3/D-1/H-1 reminders + feedback send/follow-up | [scheduler/triggers.py](src/eventbuddy/scheduler/triggers.py), [scheduler/jobs.py](src/eventbuddy/scheduler/jobs.py) |
| Reminder math | D-3/D-1/H-1 times + escalation rule (`<50%` after 2 days) | [domain/reminders.py](src/eventbuddy/domain/reminders.py) |
| Adaptive Cards | Event-overview card; reminder channel-choice card | [bot/cards/builders.py](src/eventbuddy/bot/cards/builders.py) |

## Data & integrations
- Repositories (event-scoped, sync SQLAlchemy): [data/repositories/](src/eventbuddy/data/repositories/) — `events.py`, `members.py` (registration rate, pending), `tasks.py` (due-within, by-assignee).
- ORM models / Redis / engine: [domain/models.py](src/eventbuddy/domain/models.py), [data/redis.py](src/eventbuddy/data/redis.py), [data/db.py](src/eventbuddy/data/db.py).
- Microsoft Graph (typed httpx wrapper + MSAL client-credentials token): [integrations/graph/client.py](src/eventbuddy/integrations/graph/client.py), [integrations/graph/token.py](src/eventbuddy/integrations/graph/token.py).
- LLM gateway (MaaS, OpenAI-compatible): [integrations/llm/client.py](src/eventbuddy/integrations/llm/client.py).

## Not in this phase
- Live Teams round-trip needs `MICROSOFT_APP_ID/PASSWORD` + Azure Bot messaging endpoint; DB-backed actions need reachable Postgres/Redis (`alembic upgrade head` first). See [config.py](src/eventbuddy/config.py).
- `GENERATE_REPORT` returns a stub → Phase 1.5 ([__plans__/03-phase1.5-auto-report.md](__plans__/03-phase1.5-auto-report.md)).
- DM-scoped provisioning, domain rosters, channel binding, document ingestion → [__plans__/04-amendments.md](__plans__/04-amendments.md).

## Verify locally
```bash
docker compose -f deployment/docker-compose.yml up -d db redis
venv/bin/alembic upgrade head
venv/bin/python -m pytest -q              # 45 unit
venv/bin/python -m pytest -m integration  # 3 integration (needs Postgres)
```
