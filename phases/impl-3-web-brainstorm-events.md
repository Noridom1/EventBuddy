# Implementation 3 — Web Tools + Channel Brainstorm + Event Listing (implemented)

Status: **complete** on branch `main` (implemented 2026-06-14). **255 unit tests green** (35 new), `ruff check src/ tests/` clean, `alembic heads` shows a single head `0005`. App imports + `build_orchestrator()` build cleanly.

This is the third implementation. Where Impl 1 built the **action plane** (confirmed sends + audit + scheduler) and Impl 2 the **intelligence plane** (ingestion + report + feedback), Impl 3 widens the agent's **reach and awareness**: it can search the open web like a general assistant, read and brainstorm over the live channel discussion, and list a user's events in a DM. Implementation plan: [__plans__/10-impl3-web-brainstorm-events.md](../__plans__/10-impl3-web-brainstorm-events.md).

---

## What the agent can do now (new this implementation)

| # | Capability | Tool / surface | Gate | New here? |
|---|-----------|----------------|------|-----------|
| 1 | **Search the open web** — top results (title/URL/snippet) for external facts, research, brainstorm inspiration | `web_search` | none (read-only) | **✅ new** |
| 2 | **Read a web page in full** — clean extracted text so it can read a result in depth | `web_fetch` | none (read-only) | **✅ new** |
| 3 | **Brainstorm over the channel discussion** — read the focused event channel's recent messages, summarize the ideas, and suggest directions (may web-search for inspiration) | `read_channel_discussion` | membership | **✅ new** |
| 4 | **List my events** — the events the caller is a member of or hosts, with status + role + a focused marker | `list_my_events` | none (own membership) | **✅ new** |
| — | **Scope + real `team_id` capture** (enabling) — channel-vs-DM detection and the real Teams team id, captured from the activity and stored per-event | router → graph → orchestrator | server | **✅ new** |

Cross-cutting, also new:
- **Web tools are configuration-gated** — `web_search`/`web_fetch` are registered **only** when `TAVILY_API_KEY` is set, so the agent never advertises a search capability the deployment can't fulfil.
- **Untrusted-content framing** — output from `web_search`, `web_fetch`, and `read_channel_discussion` is wrapped in an `<external_untrusted_content>` envelope, and the system prompt forbids treating it as instructions (prompt-injection guard). The dangerous actions all remain HITL-gated, so injection can at worst surface a confirm card the user must approve.
- **The standing `tenant_id`-as-`team_id` bug is fixed** (the "wide" fix) — see below.

> **Brainstorm prerequisite (load-bearing).** The agent only receives channel messages where it is `@mentioned`, and the durable transcript stores only bot turns — so the raw discussion isn't in our data. Brainstorm reads it on demand via Microsoft Graph (`/teams/{team}/channels/{channel}/messages`), which needs the **`ChannelMessage.Read.Group`** RSC permission in the Teams app manifest **and a re-install of the app to the team** (resource-specific consent — no tenant-wide admin grant). Until that's in place, brainstorm degrades to a clean "can't read this channel yet" message.

---

## The flows

**Web research.**
```
"find outdoor team-building venues in Da Nang"  →  ReAct loop:
  • web_search(query)  → top results (title/URL/snippet), wrapped untrusted
  • web_fetch(url)     → one page's main text (bounded to ~6k chars), wrapped untrusted
  • model answers, grounded in what the tools returned
no Tavily key → tools aren't registered; the agent says web search isn't available
```

**Channel brainstorm (read-only).**
```
"@EventBuddy summarize our ideas and suggest directions"  (in an event channel)
  → scope=channel → orchestrator resolves the channel's event (+ backfills its real team_id)
  → read_channel_discussion(limit):
        guards: focused event? Graph creds? bound channel? known team_id? caller a member/host?
        → graph.list_channel_messages(team_id, channel_id, limit)  (HTML stripped, system msgs dropped)
        → wrapped as untrusted external content (oldest-first)
  → (optional) web_search for inspiration
  → model replies with a summary of the ideas + concrete suggestions  (never creates events/tasks)
non-member → refused without a Graph call; missing team_id → clean degrade
```

**List my events (DM).**
```
"what events am I in?"  →  list_my_events:
  EventRepository.list_for_user(user_id)  → member events + hosted events, deduped, newest-first
  → "• <name> — <status> (your role: <role>)  ⭐ focused"
then "focus the hackathon one" → set_focus_event
```

---

## Enabling: scope detection + the real `team_id` (Part 0)

Two latent issues blocked brainstorm and are fixed here:

1. **Scope was never set on the live path.** [activity_router.py](../src/eventbuddy/bot/activity_router.py) invoked the graph without a scope, so `Orchestrator.handle` always took its `scope="personal"` default — **every Teams message, even one in a channel, was treated as a DM.** `_scope_and_team(activity)` now derives `scope` (`channel` when `conversation_type == "channel"`, else `personal`; group chats stay personal) and the `team_id` (from `channel_data.team.id`), threaded through `AgentState` → `handle` → `_build_ctx`. In channel scope the focused event is the one **bound to that channel** (`_build_channel_event_fn`), not the caller's DM focus.

2. **`team_id` was the tenant id.** Every channel Graph call passed `settings.microsoft_app_tenant_id` as the `team_id`, but Graph's `/teams/{team_id}/...` wants the team/group id — a different value. The real id is now captured from the activity and **backfilled onto `Event.teams_team_id`** on the first channel message (idempotent), and **every live channel call site** routes through it via the `_team_id_for(ev)` helper (event's stored id → configured `MICROSOFT_TEAM_ID` → tenant id fallback for back-compat):
   - reminder channel post (`_perform_send`, via a `team_id` on the pending payload),
   - channel file pull + proactive invite card (`ingest_fn`, `ChannelFilesService`),
   - Forms responses-workbook discovery (`report_fn` → `discover_workbook`),
   - new channel-message read (`read_channel_discussion`).
   Provisioning stores the team id on the event at channel-create time. (`BroadcastService` is not constructed anywhere in `src/`, so it has no live path.)

---

## What changed (files)

| Piece | What it does | File |
|---|---|---|
| Web client | Tavily `search` + `extract` (`fetch`); degrades to empty on any error | [integrations/web/client.py](../src/eventbuddy/integrations/web/client.py) *(new)* |
| Graph method | `list_channel_messages` (top-N, HTML-stripped, system msgs dropped) + `_strip_html` | [integrations/graph/client.py](../src/eventbuddy/integrations/graph/client.py) |
| Tools | `web_search`/`web_fetch` (config-gated), `list_my_events`, `read_channel_discussion`; `wrap_untrusted` + `_no_list_events`/`_no_read_channel` defaults; new `AgentDeps` fields | [agent/tools.py](../src/eventbuddy/agent/tools.py) |
| Composition root | `_team_id_for` helper + tenant→team fix at all channel call sites; `list_events_fn`, web closures, `_build_channel_event_fn`, `_build_read_channel_fn`; wired into deps + orchestrator | [agent/wiring.py](../src/eventbuddy/agent/wiring.py) |
| Orchestrator | `channel_event_fn` param; channel scope resolves the channel's event; `team_id` threaded into `_build_ctx` | [agent/orchestrator.py](../src/eventbuddy/agent/orchestrator.py) |
| Graph state | `AgentState` gains `scope` + `team_id`; `run_node` forwards them | [agent/graph.py](../src/eventbuddy/agent/graph.py) |
| Activity router | `_scope_and_team(activity)`; passes `scope`/`team_id` into the graph | [bot/activity_router.py](../src/eventbuddy/bot/activity_router.py) |
| Dev route | optional `scope`/`channel_id`/`team_id` for exercising channel scope over HTTP | [api/dev.py](../src/eventbuddy/api/dev.py) |
| Event model + repo | `teams_team_id` column; `set_team_id`, `list_for_user` | [domain/models.py](../src/eventbuddy/domain/models.py), [data/repositories/events.py](../src/eventbuddy/data/repositories/events.py) |
| Migration | `0005` — add the nullable `events.teams_team_id` column | [alembic/versions/0005_event_team_id.py](../alembic/versions/0005_event_team_id.py) *(new)* |
| Provisioning | stores the real team id on the event at channel-create time | [capabilities/provisioning.py](../src/eventbuddy/capabilities/provisioning.py) |
| System prompt | when-to-search guidance, brainstorm flow, list-events, untrusted-content rule | [agent/prompts/system.py](../src/eventbuddy/agent/prompts/system.py) |
| Config | `microsoft_team_id`, `tavily_api_key`, `web_search_max_results`, `web_search_timeout` | [config.py](../src/eventbuddy/config.py) |

**One migration (`0005`)** — adds the nullable `events.teams_team_id` column.

---

## Deploying & testing with the Bot Framework Emulator

### 1. `.env` settings (what to add for this implementation)
| Key | Needed for | Notes |
|---|---|---|
| `TAVILY_API_KEY` | `web_search` / `web_fetch` | Empty → the web tools are not registered (agent says web search is unavailable). |
| `WEB_SEARCH_MAX_RESULTS` / `WEB_SEARCH_TIMEOUT` | web tool tuning | Optional; default 5 results / 15s. |
| `MICROSOFT_TEAM_ID` | channel Graph calls (create-channel + fallback) | The team to create event channels under, and the fallback before an event's real `teams_team_id` is observed. Empty → falls back to the tenant id (single-team demo). |
| `GRAPH_TENANT_ID` / `GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET` | brainstorm (reads channel messages) | Without them brainstorm degrades to a clean message. |

> **Teams manifest (RSC):** add `ChannelMessage.Read.Group` to `authorization.permissions.resourceSpecific` and **re-install the app to the team**. This is the only non-code prerequisite for brainstorm; no tenant-wide admin consent required.

### 2. Migrate the DB
The container entrypoint runs `alembic upgrade head` on boot (best-effort). By hand: `venv/bin/alembic upgrade head` — applies `0005` (the `teams_team_id` column).

### 3. Walk the Impl 3 flows in the Emulator
| Say | Expect |
|---|---|
| `find some icebreaker activities for a 30-person workshop` (DM) | the agent calls `web_search` (and maybe `web_fetch`) and answers with current ideas — or says web search isn't configured |
| `what events am I in?` (DM) | a list of your events with status + role + a ⭐ on the focused one; then `focus the …` works |
| `@EventBuddy summarize our ideas and suggest directions` (in an event channel) | a summary of the channel discussion + concrete suggestions; nothing is created |

### 4. ngrok-free alternative (scripted, `DEV_ROUTES_ENABLED=true`)
The dev route now accepts `scope`/`channel_id`/`team_id`, so channel brainstorm can be exercised over HTTP:
```bash
EP=$(make -s endpoint)
# DM web search / list events
curl -s $EP/api/dev/handle -H 'content-type: application/json' \
  -d '{"user_id":"dev-user","text":"what events am I in?"}' | jq -r '.reply'
# Channel brainstorm (channel scope + a real team id)
curl -s $EP/api/dev/handle -H 'content-type: application/json' \
  -d '{"user_id":"dev-user","text":"summarize our ideas","scope":"channel","channel_id":"<ch>","team_id":"<team>"}' | jq -r '.reply'
```

---

## Tests (35 new unit)
[test_web_client.py](../tests/unit/test_web_client.py) (Tavily search/fetch mapping + degradation), [test_channel_messages.py](../tests/unit/test_channel_messages.py) (`list_channel_messages` parse/strip/filter), [test_event_listing.py](../tests/unit/test_event_listing.py) (`list_for_user` member+host join, dedup, `set_team_id`), [test_web_and_list_tools.py](../tests/unit/test_web_and_list_tools.py) (config-gated web-tool registration + delegation, no identity in tool schemas), [test_scope_routing.py](../tests/unit/test_scope_routing.py) (`_scope_and_team`, channel-event resolve + team-id backfill, `_build_ctx` routing), [test_brainstorm.py](../tests/unit/test_brainstorm.py) (membership guard, host access, missing-team-id/no-creds degrade, untrusted wrap, read-only). Updated: [test_provisioning.py](../tests/unit/test_provisioning.py) (asserts team id stored), [test_graph_wrapper.py](../tests/unit/test_graph_wrapper.py) (scope/team_id forwarding).

---

## Notes / deferred
- **`.env.example`** — add `MICROSOFT_TEAM_ID=`, `TAVILY_API_KEY=`, `WEB_SEARCH_MAX_RESULTS=`, `WEB_SEARCH_TIMEOUT=`. (The agent could not write that file; it lives outside the writable path. `config.py` documents the defaults.)
- **RSC + app re-install** — the only non-code prerequisite for brainstorm (`ChannelMessage.Read.Group`).
- **Brainstorm is read-only** (decided) — it summarizes + suggests; turning a suggestion into a task/event is left to the user via the existing tools.
- **On-demand channel read, not passive ingestion** — the alternative (store every channel message in the transcript) was considered and deferred; on-demand read covers brainstorm without the extra subscription/storage infrastructure.
- **Web result caching** (Redis) — a possible latency/cost optimization, not built.
- **Migration applied for chain integrity only** here (single head `0005`); it runs against live Postgres via the entrypoint / `alembic upgrade head`.
