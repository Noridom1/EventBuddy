# Implementation 6 — "Preparing response" typing indicator (implemented)

Status: **complete** on branch `impl-6-typing-indicator` (implemented 2026-06-15). **391 unit tests green** (3 new), `ruff check src/ tests/` clean, no migrations. Implementation plan: [__plans__/14-typing-indicator.md](../__plans__/14-typing-indicator.md).

A small UX implementation: while the agent prepares a reply, the user now sees the native Teams **typing indicator** (the animated "EventBuddy is typing…" dots) — a loading-spinner signal — instead of staring at a silent chat until the answer lands. The indicator persists for the *whole* turn, however long the LLM tool-calling loop runs, and is dismissed automatically when the reply is sent.

---

## What changed

| Surface | Before | After |
|---|---|---|
| Message turn ([activity_router.py](../src/eventbuddy/bot/activity_router.py)) | `graph.invoke` blocked the event loop; the user waited with no feedback | typing dots shown immediately and re-sent every 2.5s until the reply is ready |
| Confirm-click / sign-in / invoke turns | instantaneous | unchanged (no indicator — nothing to wait for) |
| Dev HTTP route ([api/dev.py](../src/eventbuddy/api/dev.py)) | no `TurnContext` | unchanged (out of scope) |

---

## The core constraint and the fix

`EventBuddyBot.on_message_activity` is `async`, but the turn's work — `self._graph.invoke(...)` → `Orchestrator.handle` → the `create_react_agent` runner (MaaS HTTP calls) — is **fully synchronous and blocks the event loop**. (That sync-inline chain is load-bearing: the `turn_artifacts` / ToolTrace `ContextVar`s rely on it so a card emitted deep in a tool body is visible to the router after `invoke` returns.)

Because the loop is blocked during `invoke`, an in-loop `asyncio` task created to re-send typing dots would **never get scheduled** — so a single pre-invoke dot would simply fade after a few seconds, leaving the user with nothing again. The fix (Plan 14, Option B):

1. **Offload the blocking `invoke` to a thread executor** (`loop.run_in_executor`). This frees the event loop so a background task *can* re-send the typing activity on an interval.
2. **A background typing loop** ([bot/typing.py](../src/eventbuddy/bot/typing.py)) sends one dot immediately, then re-sends every 2.5s — comfortably inside the Teams fade window — until the `async with typing_indicator(...)` block exits and cancels it.
3. **Propagate the turn-artifacts ContextVar into the worker thread** via `contextvars.copy_context()` captured *after* `begin_artifacts()`, run with `ctx.run(self._graph.invoke, payload)`. Without this, cards emitted in a tool body (running off-loop) wouldn't reach the router. The delegated-Graph-token and ToolTrace ContextVars are set *inside* the runner (below `invoke`), so they already live in the worker thread.

```
on_message_activity (async, event loop)
  ├─ begin_artifacts() ── sets turn-artifacts ContextVar
  ├─ ctx = copy_context()                    ← captures it for the worker thread
  ├─ async with typing_indicator(turn_context):   ← dot now + every 2.5s
  │     result = await loop.run_in_executor(None, lambda: ctx.run(graph.invoke, payload))
  └─ send reply + cards (clears the indicator)
```

Everything downstream of `invoke` (reply text, the cards-as-attachments loop, the sign-in nudge) is unchanged.

---

## Graceful degradation

Every typing send is wrapped — a transient connector error or a surface that doesn't render the indicator becomes a silent no-op, never a broken turn. The indicator is best-effort decoration, never on the critical path (CLAUDE.md invariant preserved).

---

## New behavior to be aware of: turns no longer serialize on the loop

Offloading `invoke` off the event loop means turns for **different** threads can now run in parallel worker threads (previously each turn fully blocked one worker, implicitly serializing them). Same-thread races are still serialized by the existing `session_lock` ([agent/memory.py](../src/eventbuddy/agent/memory.py)); each turn opens its own `session_scope()` DB session, so per-turn DB isolation holds. This is the main thing to watch if concurrency-related issues surface in-tenant.

---

## Files

- **New:** [src/eventbuddy/bot/typing.py](../src/eventbuddy/bot/typing.py) — `typing_indicator(turn_context)` async context manager.
- **Changed:** [src/eventbuddy/bot/activity_router.py](../src/eventbuddy/bot/activity_router.py) — executor offload + `copy_context()` + indicator wrap around the message-turn invoke.
- **Tests:** [tests/unit/test_typing_indicator.py](../tests/unit/test_typing_indicator.py) (new — immediate dot, clean cancel, send-failure tolerance); [tests/unit/test_echo_bot.py](../tests/unit/test_echo_bot.py) and [tests/unit/test_activity_router_hitl.py](../tests/unit/test_activity_router_hitl.py) updated to look past the typing activities now emitted every turn.

---

## Follow-ups (out of scope)

- **Progressive / streaming replies** — step messages ("Searching files…" → "Drafting…") or token streaming would be a richer signal than dots, but need the runner to emit progress events. Track separately if dots prove insufficient.
- Interval (2.5s) validated against the Teams fade window in-tenant.
