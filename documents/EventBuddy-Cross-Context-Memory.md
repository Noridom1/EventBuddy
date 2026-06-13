# EventBuddy — Time-Aware & Cross-Context Memory (DM ← Event)

*Two related memory upgrades: (A) making the agent **time-aware** — it learns *when* each
message was sent — and (B) letting a 1-1 DM assistant **borrow conversational context** from a
shared event thread when the user focuses on that event. (A) is the foundation: a cross-context
snapshot is only trustworthy if the model knows when the discussion happened. Design rationale
+ the security model below. Companion to [EventBuddy-Agent-Memory.md](EventBuddy-Agent-Memory.md);
implementation plan in [__plans__/07-phase1.9-cross-context-memory.md](../__plans__/07-phase1.9-cross-context-memory.md).*

---

## Part A — Time-awareness

### A.1 The problem

The agent currently has **no idea when any message was sent**, and isn't even told the current
time:

- Human turns are built by [`ctx.tag()`](../src/eventbuddy/agent/context.py#L34-L39) as
  `HumanMessage(content, name)` — **no timestamp**.
- The transcript's [`_to_message`](../src/eventbuddy/agent/transcript.py#L92-L98) **drops
  `created_at`** when rebuilding history; and `created_at` itself is *synthetic flush-time*
  (`datetime.now(UTC)` with incrementing microseconds for ordering —
  [transcript.py:57-66](../src/eventbuddy/agent/transcript.py#L57-L66)), **not** the real
  send-time.
- [`system_prompt`](../src/eventbuddy/agent/prompts/system.py) injects no "now," so even a
  message that says "deadline tomorrow" can't be anchored.

For an event assistant this is a real gap: "this task was assigned 2 days ago, the deadline is
close" is unanswerable.

### A.2 The real send-time is already at ingress — and discarded

Every inbound Teams message is a Bot Framework `Activity` carrying `activity.timestamp`
(channel-set UTC) and `activity.id`. But [activity_router.py:11-17](../src/eventbuddy/bot/activity_router.py#L11-L17)
reads only `user_id`, `channel_id`, `text`. **We don't need a Teams/Graph API call to know when
our own messages were sent — we just stopped throwing the timestamp away.** (Microsoft Graph
*can* fetch a message's `createdDateTime` by id, but that's a new permissioned surface —
`ChannelMessage.Read.All`, admin consent — and `GraphClient` has no read method today; it's only
worth it for messages *outside* our memory. Deferred.)

### A.3 The design — store at L1 + L2, keep L3 clean

Capture `activity.timestamp` once at ingress and thread it through
`handle(..., sent_at=) → RequestContext.sent_at → ctx.tag()`:

| Layer | Stores "when"? | How |
|-------|----------------|-----|
| **L1** working window | ✅ | `HumanMessage.additional_kwargs["sent_at"]` (ISO-UTC); rides in the Redis checkpointer automatically |
| **L2** transcript | ✅ | a **new `sent_at` column** (migration), distinct from the `created_at` ordering field; the *real* send-time, not flush-time |
| **L3** summary | ❌ | unchanged — the summarizer reads only `role`+`content`, so the gist stays time-agnostic by design |

**Making the model actually *see* it.** The LLM only reads message `content`; an
`additional_kwargs` field or a DB column does not reach it. So time is surfaced deliberately,
keeping stored `content` pure:

1. **"Now" in the system prompt** — without a current-time anchor, no stamp is interpretable.
2. **Rendered stamps only where history is injected** — a compact `[2026-06-11 14:30 UTC]`
   prefix on the rehydrated transcript tail and the event snapshot (Part B). Live-window turns
   are *not* stamped (they read as "~now"; the prompt's "now" covers them) — saving tokens in a
   tight 4096-token window.

This keeps times out of what the summarizer reads (so L3 stays clean by construction) rather
than baking them into `content`.

---

## Part B — Cross-context memory

### 1. The problem

EventBuddy has two conversation scopes, each its own three-layer memory keyed by `thread_id`
([context.py](../src/eventbuddy/agent/context.py#L26-L32)):

- **1-1 DM** — `dm:{user_id}` — a private, everyday assistant for an individual's
  event-related tasks.
- **Event channel** — `event:{channel_id}` — one shared thread across all members of an
  event.

These two threads do **not** share memory. So when a user opens a DM and says *"focus on the
Launch Party event,"* the DM agent has the user's private history but **no awareness of what
was discussed in the event's shared channel** — decisions, commitments, dates, open
questions. The DM assistant is supposed to help with *that event's* work, so it needs that
context.

This is distinct from **event state** (tasks, roster, dates, the report), which the DM
already reaches through the focused-event tools ([list_my_tasks](../src/eventbuddy/agent/tools.py#L160-L165),
[generate_report](../src/eventbuddy/agent/tools.py#L167-L172)) scoped by
`current_event_id`. What's missing is the **shared conversational memory** — Layers 2 and 3
of the event thread.

---

## 2. The idea

When a DM user focuses on an event, surface a compact snapshot of that event's shared
conversation (its rolling **summary** + a short **transcript tail**) into the DM so the
assistant is grounded in it. The user's own mental model:

> *Layer 1 = right now, Layer 2 = day-to-day, Layer 3 = lifelong.*

Cross-context fetch reads the event thread's **Layer 3 (summary)** and **Layer 2 (transcript
tail)** — never Layer 1. Layer 1 (the raw Redis working window) carries tool-call/result
plumbing and is noisy; Layers 2 + 3 are the clean, model-ready gist — exactly what the
runner's existing [`_seed_messages`](../src/eventbuddy/agent/runner.py#L107-L117) already
composes for cold-start recall. We reuse that shape, pointed at the *event* thread.

```
  DM thread  dm:{user_id}                       Event thread  event:{channel_id}
  ┌───────────────────────────┐                 ┌───────────────────────────┐
  │ L1 working window (Redis) │                 │ L1 working window (Redis) │
  │ L2 transcript (Postgres)  │   focus on      │ L2 transcript (Postgres)  │──┐
  │ L3 summary (Postgres)     │   event 'X'     │ L3 summary (Postgres)     │──┤ read L3+L2
  └───────────────────────────┘      │          └───────────────────────────┘  │  (members only)
              ▲                       │                                         │
              └───────────────────────┴── inject "Context from event 'X': …" ◄──┘
                       (one-directional: DM may read event; event never reads a DM)
```

---

## 3. The security model (non-negotiable)

The cross-cutting invariant ([tools.py:1-14](../src/eventbuddy/agent/tools.py#L1-L14)):
identity, role, scope, and **focused-event come from the server-built `RequestContext`,
never from model arguments.** Reading another thread's shared conversation is a privacy-
sensitive cross-tenant read, so it must obey three rules:

1. **The event is always `ctx.current_event_id`** — the server-resolved focused event — and
   is **never a tool argument**. A model (or a crafted user prompt) must not be able to name
   an arbitrary event/thread and pull its private conversation. This is why the fetch tool
   takes **no** event parameter, exactly like `list_my_tasks` / `generate_report`.
2. **Membership is enforced server-side.** Before returning any event memory, verify the
   caller is a member of that event via
   [`MemberRepository.get_by_user(event_id, ctx.user_id)`](../src/eventbuddy/data/repositories/members.py).
   Non-member → return nothing (graceful, not an error).
3. **One-directional.** A DM may read its focused event's shared memory; the event channel
   must **never** read a user's private DM. Don't let this creep.

A single server-side helper — `load_event_context(user_id, event_id) -> str` — owns all
three checks, so the guard lives in exactly one place.

---

## 4. Resolving the event thread (already possible today)

Focus gives an `event_id`; event memory is keyed `event:{channel_id}`. The mapping already
exists in the data layer — **no new binding is required**:

- [`Event.teams_channel_id`](../src/eventbuddy/domain/models.py#L15) holds the bound channel.
- `EventRepository.get(event_id).teams_channel_id` → the channel id → thread key
  `event:{teams_channel_id}`.

If the event has **no** channel bound yet (`teams_channel_id is None` — e.g. an event created
from a DM that was never provisioned into a channel), there is simply no shared thread to
read → the helper returns empty and the assistant proceeds on DM context alone. Graceful
degradation, consistent with the rest of the system.

---

## 5. Two delivery options (and the recommendation)

Both options reduce to *"a tool returns the event-context string as its result"* — the model
reads it as a `ToolMessage`. They differ in **when** it fires.

| | **Option B — fold into focus** (deterministic) | **Option A — separate refresh tool** (on-demand) |
|---|---|---|
| Trigger | automatically inside `set_focus_event` on success | model calls `get_event_context()` when it wants |
| Grounding | **guaranteed** right after focus | only if the model chooses to call |
| Freshness | one-shot snapshot, can go stale | fresh on every call |
| Model reliance | none | yes (judgment) |

**Recommendation: hybrid, lead with B.** `set_focus_event` appends the event-context snapshot
to its result so the assistant is grounded the moment the user focuses (no reliance on model
judgment). A lightweight `get_event_context()` tool over the *same* helper lets the model
re-pull fresh detail later, which matters because the snapshot — living in the DM working
window — is subject to the 4096-token trimmer and 24h TTL and will eventually age out.

**Optional enhancement (not core):** extend [`_seed_messages`](../src/eventbuddy/agent/runner.py#L107-L117)
so that when a DM cold-starts *and* `current_event_id` is set, the seed also includes the
focused event's summary. This keeps focus "sticky" across a TTL expiry without a model call.
Deferred — the tool path covers the primary need.

Cross-context fetch only makes sense in **DM scope**; inside an event channel the event
memory *is* the live window, so the helper is a no-op (or skipped) when `ctx.scope == "channel"`.

---

## 6. Where it plugs into the existing wiring

The capability-closure pattern in [wiring.py](../src/eventbuddy/agent/wiring.py) is the seam:
define `event_context_fn` alongside the existing `provision_fn` / `resolve_event_fn` / … ,
give it the `transcript` + `summarizer` handles and a DB session, expose it on `AgentDeps`,
and call it from the tool bodies. This keeps the DRY composition-root convention intact and
the tool/`handle(...)` signatures stable.

```mermaid
sequenceDiagram
    autonumber
    participant U as DM user
    participant A as Agent (DM thread)
    participant F as set_focus_event tool
    participant H as load_event_context(ctx)
    participant DB as Postgres (members, events)
    participant L23 as Event L3 summary + L2 transcript

    U->>A: "focus on the Launch Party"
    A->>F: set_focus_event("Launch Party")
    F->>F: resolve → event_id; session.set_current_event
    F->>H: load_event_context(user_id, event_id)
    H->>DB: member of event? (MemberRepository)
    alt is a member AND event has a channel
        H->>DB: event.teams_channel_id → event:{channel_id}
        H->>L23: get_summary + rehydrate(tail)
        L23-->>H: "summary … recent discussion …"
        H-->>F: context string
    else not a member / no channel bound
        H-->>F: "" (graceful no-op)
    end
    F-->>A: "Focused on 'Launch Party'.\n\nContext from this event: …"
    A-->>U: grounded reply
```

---

## 7. Prerequisites & sequencing

1. **Transcript flush (hard blocker).** Today `flush_window` is implemented but **never
   called in the live path** ([EventBuddy-Agent-Memory.md §3](EventBuddy-Agent-Memory.md)),
   so event threads accumulate nothing in Layers 2/3 — there is nothing to fetch *or* to
   stamp with a send-time. Wiring the flush (for *all* threads, channel included) is the
   foundation both parts stand on.
2. **Part A — time-awareness** (do first): capture `activity.timestamp` at ingress → `sent_at`
   on L1/L2 (+ migration) → "now" in the system prompt → rendered stamps at injection points.
   The Part-B snapshot then carries trustworthy times.
3. **Event→thread resolution** — available now via `Event.teams_channel_id`; just add a small
   `event_thread_id(event_id)` helper + the no-channel no-op.
4. **`load_event_context` helper** with the membership guard (the single guarded, *timestamped*
   L2+L3 read).
5. **Option B** — fold the snapshot into `set_focus_event`.
6. **Option A** — add `get_event_context()` over the same helper.

See the implementation plan: [__plans__/07-phase1.9-cross-context-memory.md](../__plans__/07-phase1.9-cross-context-memory.md).
