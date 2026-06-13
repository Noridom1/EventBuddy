# Phase 1.9 — Time-Aware & Cross-Context Memory (implemented)

Status: **complete** on branch `phase-1.8-tool-error-surfacing` (implemented 2026-06-13). 129 unit tests green, `ruff check src/ tests/` clean. Manual end-to-end against live Postgres/Redis/MaaS (plan Step 12) still pending.

Two related memory upgrades, building on the Phase 1.7 layered stack:

- **Part A — time-awareness.** The agent now learns *when* each message was sent and *what time it is now*, so it can reason about recency ("assigned 2 days ago", "deadline tomorrow").
- **Part B — cross-context memory.** When a 1-1 DM user focuses on an event, the DM assistant borrows that event's shared-channel conversation (L3 summary + L2 transcript tail) — a one-directional, membership-gated read.

Design rationale + the security model: [documents/EventBuddy-Cross-Context-Memory.md](../documents/EventBuddy-Cross-Context-Memory.md). Implementation plan: [__plans__/07-phase1.9-cross-context-memory.md](../__plans__/07-phase1.9-cross-context-memory.md). Companion to the memory deep-dive [documents/EventBuddy-Agent-Memory.md](../documents/EventBuddy-Agent-Memory.md).

## Prerequisite fixed first — the durable write path

Before Phase 1.9, `flush_window` existed but was **never called in the live path**, so Layers 2/3 stayed empty in production — there was nothing to summarize, rehydrate, *or* cross-read. This phase wires a live per-turn write via **`Transcript.record_turn(...)`**, called by `AgentRunner._record_turn` after every `agent.invoke` (best-effort; a DB hiccup never breaks the reply).

`record_turn` was chosen over the plan's original `flush_window(full_window)`: `flush_window`'s high-water-mark count-slice assumes the **full** window is passed each time, but a cold-seeded window holds only a *tail*, so the count slice would mis-skip genuinely-new turns and permanently starve L2 after the first 24h TTL expiry. `record_turn` appends exactly this turn's user+assistant pair — disjoint per turn, correct regardless of window state. `flush_window` is retained for batch use and also learned `sent_at`.

## Part A — time-awareness

Real send-time was already arriving at ingress (`activity.timestamp`, channel-set UTC) and being discarded. We stopped throwing it away and surfaced it deliberately, keeping stored `content` pure so the L3 summarizer stays time-agnostic.

| Piece | What it does | File |
|---|---|---|
| Ingress capture | `activity.timestamp` read and threaded into the graph invoke | [bot/activity_router.py](../src/eventbuddy/bot/activity_router.py) |
| Stable signature | `handle(..., sent_at=None)` → `RequestContext.sent_at` (additive, defaulted) | [agent/orchestrator.py](../src/eventbuddy/agent/orchestrator.py), [agent/graph.py](../src/eventbuddy/agent/graph.py) |
| L1 carry | `ctx.tag()` stamps `HumanMessage.additional_kwargs["sent_at"]` (ISO-UTC) | [agent/context.py](../src/eventbuddy/agent/context.py) |
| L2 column | new `sent_at` column (real send-time, distinct from synthetic `created_at` ordering field) | [domain/models.py](../src/eventbuddy/domain/models.py), [alembic/versions/0003_message_sent_at.py](../alembic/versions/0003_message_sent_at.py) |
| L3 untouched | summarizer reads only `role`+`content` → gist stays time-agnostic by design | [agent/summarizer.py](../src/eventbuddy/agent/summarizer.py) |
| "Now" in prompt | `system_prompt(ctx, now=...)` injects current UTC time + a recency-reasoning nudge | [agent/prompts/system.py](../src/eventbuddy/agent/prompts/system.py) |
| Rendered stamps | `[2026-06-11 14:30 UTC]` prefix on injected history only (rehydrated tail + event snapshot); live-window turns read as "~now" | [agent/transcript.py](../src/eventbuddy/agent/transcript.py) (`sent_at_prefix`), [agent/runner.py](../src/eventbuddy/agent/runner.py) (`_stamp`) |

## Part B — cross-context memory

When a DM user focuses on an event, surface a compact snapshot of that event's shared conversation (rolling **summary** + short **transcript tail**) into the DM. Reuses the same shape as cold-start seeding, pointed at the *event* thread.

| Piece | What it does | File |
|---|---|---|
| Thread resolution | `event_thread_id(channel_id)` → `event:{channel_id}`; no channel bound → no-op | [agent/context.py](../src/eventbuddy/agent/context.py) |
| Guarded read helper | `event_context_fn(user_id, event_id)` — single place owning all three security checks; reads L3 `get_summary` + L2 `rehydrate(tail)`, formats the snapshot | [agent/wiring.py](../src/eventbuddy/agent/wiring.py) |
| Option B (lead) | `set_focus_event` folds the snapshot into its result on success (DM scope only) → guaranteed grounding right after focus | [agent/tools.py](../src/eventbuddy/agent/tools.py) |
| Option A (on-demand) | `get_event_context()` tool over the *same* helper → model re-pulls fresh detail after the snapshot ages out | [agent/tools.py](../src/eventbuddy/agent/tools.py) |

### Security model (non-negotiable)
1. **Event is always `ctx.current_event_id`** — the server-resolved focused event, **never a tool argument**. The fetch tool takes **no** event parameter (a test asserts the schema is event-arg-free), so a crafted prompt can't name an arbitrary thread.
2. **Membership enforced server-side** via `MemberRepository.get_by_user(event_id, user_id)`. Non-member → returns empty (graceful, not an error).
3. **One-directional.** A DM may read its focused event's shared memory; an event channel **never** reads a user's private DM.

## Tests
- [test_prompts.py](../tests/unit/test_prompts.py) — "now" injected into the system prompt.
- [test_transcript.py](../tests/unit/test_transcript.py) — `record_turn` persists/defaults `sent_at`; rehydrate round-trips it; `flush_window` learned it.
- [test_agent_runner.py](../tests/unit/test_agent_runner.py) — `record_turn` called after each turn, best-effort on failure, seeded tail stamped while the live turn is not.
- [test_tools.py](../tests/unit/test_tools.py) — `get_event_context` / focus snapshot; no event arg in the tool schema.
- [test_cross_context.py](../tests/unit/test_cross_context.py) (new) — member reads, non-member/no-channel/no-focus all return empty.
- [test_orchestrator_conversational.py](../tests/unit/test_orchestrator_conversational.py), [test_graph_wrapper.py](../tests/unit/test_graph_wrapper.py) — `sent_at` threads through and defaults when absent.

## Notes / not in this phase
- **Cold-start seeding is unchanged in shape:** an empty L1 window still seeds L3 summary (SystemMessage) **plus** the L2 `rehydrate` tail (≤4096-token budget, oldest-first). The 4096 here is the rehydrate budget, separate from the L1 pre-model trimmer (also 4096) that bounds what the model sees per call. `record_turn` (the write path) is per-turn and unbounded by 4096.
- **Sticky focus across TTL expiry** (extending `_seed_messages` to fold the focused event's summary on a DM cold-start) is deferred — the tool path covers the primary need.
- Reading another channel's message history via Microsoft Graph (`ChannelMessage.Read.All`) is deferred — we only surface conversation already in our own memory.
- Run `alembic upgrade head` (now revision `0003`) before the live path so the `sent_at` column exists.
