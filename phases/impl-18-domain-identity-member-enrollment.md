# Implementation 18 — Domain-Identity Member Enrollment & Sync (implemented)

Status: **complete** on branch `impl-10-agent-reasoning-trace-logging` (implemented 2026-06-16). **496 unit tests green** (14 new), `ruff check src/ tests/` clean, **one migration** (`0009`), no dependency changes. Implementation plan: [__plans__/18-domain-identity-member-enrollment.md](../__plans__/18-domain-identity-member-enrollment.md).

This is the eleventh implementation. It changes **who an event's members are** and **how the same human is recognized across conversations** — so initiating an event in a group chat enrolls everyone, and each member can then see, focus, and track that event from their own 1-1 DM.

---

## The problem it solves

Before this change, setting up an event in a group chat enrolled **only the caller**. `setup_event` ([wiring.py](../src/eventbuddy/agent/wiring.py)) added one `EventMember` (the poster, as host); the read-only `list_members` tool could *display* the chat roster (name + email) but never wrote it back, and per-speaker auto-enroll only added people once *they* posted. Worse, every per-user lookup keyed on the Bot Framework `from_property.id` (a per-conversation `29:…` id) — which does **not** line up with the AAD `userId` that Microsoft Graph returns for chat members. So even enrolling from the Graph roster wouldn't have matched a DM lookup, and a member opening their DM saw none of their events.

## The core idea — a member is an identity *set*

A member is now matched by **any** of three keys ([domain/identity.py](../src/eventbuddy/domain/identity.py) `CallerIdentity`):

- **`aad_object_id`** — the AAD directory GUID. Rides on every activity as `from_property.aad_object_id` **and** is exactly the `userId` Graph returns for a chat/channel member. The zero-sign-in cross-context bridge.
- **`email`** — the corporate address (the domain identity); captured from the Graph roster, used for display and as a second join key (also lines up roster/task files).
- **`teams_user_id`** — the legacy Bot Framework id, kept for back-compat and backfilled onto the identity row the first time a member posts/DMs.

A stored member matches the caller when any stored column equals any known identity value (`member_identity_clause` in [data/repositories/members.py](../src/eventbuddy/data/repositories/members.py)).

## What changed

- **Schema** — `event_members.aad_object_id` (nullable, indexed); migration [`0009`](../alembic/versions/0009_member_aad_object_id.py). Legacy rows keep it NULL and match by `teams_user_id`/`email` until backfilled.
- **Identity plumbing** — `RequestContext` gains `aad_object_id` + `user_email` and an `.identity` property; the activity router reads `from_property.aad_object_id` and resolves the caller's own email via Graph `/me` (cached in Redis by AAD id). Threaded through `graph.py` → `Orchestrator.handle` → `_build_ctx`.
- **Repositories** — `MemberRepository.get_by_identity` + `upsert_member` (idempotent merge/backfill, never downgrades role), `EventRepository.list_for_identity`, `TaskRepository.by_assignee_identity`.
- **Enroll-all** — `setup_event` now runs a new **roster-sync closure** (`_build_sync_members_fn`): `list_chat_members`/`list_channel_members` → diff by identity → `upsert_member` the missing ones. The caller's own Graph row is merged onto their host row via their BF id, so the host is never duplicated. Non-AAD/guest members are skipped + counted (no silent caps).
- **On-demand sync** — new `sync_event_members` tool: re-scan the group/channel and add anyone missing (group: any participant; channel: host/moderator). For "update the members / new people joined".
- **DM recognition** — `list_my_events`, `set_focus_event`/`resolve_event`, `list_my_tasks`/`update_task` ownership, the DM→event `event_context_fn` membership gate, and the `role_resolver` all match by identity now.
- **Backfill on touch** — per-speaker auto-enroll became an upsert-by-identity, so a member enrolled by AAD id/email gets their BF id filled onto the same row when they next post.

## Graceful degradation preserved

Host not signed in at setup → only the caller is enrolled and the existing sign-in auto-prompt fires; the roster sync returns a clean "sign in so I can read the group's members." Graph 403 / no creds → clean message, never raises. No AAD id and no email for a member → skipped (counted). No identity at all → falls back to `teams_user_id` matching (prior behavior). Both the LLM and regex router paths keep working (the closures accept a bare `user_id` and build an identity from it).

## Operational note

Roster enrollment reuses Impl 8's member listing, so it needs the delegated **`ChatMember.Read`** scope consented (and `User.Read` for `/me` email). Without them the feature degrades to a clean message — confirm with IT (see the Graph permissions ledger / `teams-integration-onboarding` memory). Sync is **additive** in v1 — members who leave the group are not pruned.

## Tests

New: [tests/unit/test_member_identity.py](../tests/unit/test_member_identity.py) (identity matching, upsert backfill/no-downgrade, `list_for_identity` group→DM, `by_assignee_identity` by email, sync enroll-all/idempotent/host-merge/degrade/channel-scope, setup enroll-all, autoenroll backfill) + `sync_event_members` tool tests in [test_action_tools.py](../tests/unit/test_action_tools.py). Updated interface assertions in `test_tools.py`, `test_web_and_list_tools.py`, `test_graph_wrapper.py`, `test_orchestrator_conversational.py`.
