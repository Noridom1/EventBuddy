# EventBuddy — Flat Peer Permissions in Group Chats

**Status:** Implemented · **Date:** 2026-06-16

## Decision

In a **Teams group chat**, EventBuddy treats every participant as an **equal peer**. There is no
host / moderator / member split in group scope — everyone resolves to `moderator`, so any
participant can run the privileged actions (read a participant roster, send reminders/mail,
ingest files, set feedback sources, rebind the conversation's event, update any task).

This leaves the other two scopes unchanged:

| Scope | Resolved role | Rationale |
|-------|---------------|-----------|
| **1-1 DM** (`personal`) | `host` | The user is the event leader acting privately. |
| **Group chat** (`group`) | `moderator` (everyone) | Flat peer space — invite-only collaboration; all participants act. |
| **Team channel** (`channel`) | real `EventMember.role` (default `member`) | Team-backed, org roles are meaningful; membership is the source of truth. |

## Why

A group chat is an invite-only space whose members are already trusted collaborators co-running
an event. Forcing a host/moderator gate there produced the failure that motivated this change: a
participant asked EventBuddy to read the participant list and got *"requires Host or Moderator"* —
even though, as a group-chat peer, they should be able to. Per-member role bookkeeping inside an
ad-hoc group chat is friction without a security benefit.

Safety is preserved by two existing mechanisms, untouched by this change:

- **HITL confirmation card** — every outbound side-effect (mail, reminders) still requires an
  explicit Adaptive-Card confirmation; nothing sends silently.
- **Scope isolation** — the elevation applies *only* to group scope. Team channels keep their
  real `EventMember` roles, and a 1-1 DM stays host-only to its single participant.

`moderator` (not `host`) is the chosen rank: every caller-facing gate checks `>= moderator`, and
no gate compares the *resolved* caller role to `host` exactly (the only `== "host"` checks are on
stored `EventMember` rows for picking notification recipients, and on `event.host_user_id` for
ownership — neither is the resolved caller role). So `moderator` satisfies all gates while keeping
semantics honest: a group peer can *act* but is not the event's owner.

## Where it lives (single seam)

Roles are resolved in exactly one place and read everywhere else, so the behaviour is two edits:

- [`_default_role`](../src/eventbuddy/agent/orchestrator.py) — the role policy: `personal → host`,
  `group → moderator`, else `member`. Group ignores any focused `event_id`.
- The `role_resolver` closure in [`wiring.py`](../src/eventbuddy/agent/wiring.py) — short-circuits
  group scope **before** the `EventMember` lookup, so a focused event where the caller's row is
  `member` never downgrades a group peer.

Everything downstream inherits the resolved role automatically:

- the `_role_allows(ctx, "moderator")` gates in [`tools.py`](../src/eventbuddy/agent/tools.py),
- the HITL confirm re-auth in [`confirm.py`](../src/eventbuddy/bot/confirm.py) (re-resolves through
  the same resolver at card-click time → consistent),
- `update_task_fn` and the setup-rebind gate in `wiring.py`.

The system prompt's group-chat framing tells the model the same thing
([`prompts/system.py`](../src/eventbuddy/agent/prompts/system.py)): *"Everyone here is an equal
peer — any participant may run any action."*

## Tests

[`tests/unit/test_role_resolution.py`](../tests/unit/test_role_resolution.py) covers the policy
(`_default_role` per scope, incl. group ignoring a focused event) and the orchestrator seam (a
group participant resolves to `moderator` even when an event is bound; a DM participant resolves
to `host`).
