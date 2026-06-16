# Implementation 19 — Agent-Controlled Merge/Separate for Teams Messages (implemented)

Status: **complete** on branch `impl-19-personalized-teams-messages` (implemented 2026-06-16). **508 unit tests green** (9 new), `ruff check src/ tests/` clean, **no migrations**, no schema / Redis-key / config / dependency changes. Implementation plan: [__plans__/19-impl10-personalized-teams-messages.md](../__plans__/19-impl10-personalized-teams-messages.md).

This implementation lets the agent send **personalized (per-recipient) Teams messages** and **decide for itself** whether they are confirmed as **one consolidated card** or as **separate cards** — replacing the prior design that assumed "one shared message, one confirmation" and actively instructed the model never to personalize.

---

## The problem it solves

In live testing an organizer asked the bot to *"send each member the details of their own tasks."* The whole `send_teams_message` path was built around **one message → many recipients → one confirmation**:

- **The tool** ([tools.py](../src/eventbuddy/agent/tools.py)) — `send_teams_message(recipients, message)` took a single `message` for all `recipients`, and its docstring commanded: *"do NOT call this once per person."* There was no way to express "Phúc gets message A, Thơ gets message B."
- **The coalescer** ([wiring.py `coalesce_teams_dm_cards`](../src/eventbuddy/agent/wiring.py)) decided merge-vs-separate **implicitly by text equality** — same text merged, different text passed through. The agent never chose; the outcome fell out of whether the strings happened to match.
- **The dispatcher** ([wiring.py `_perform_send`](../src/eventbuddy/agent/wiring.py)) sent the single shared `text` to every target.

So the agent could neither keep personalized messages separate on purpose, nor fold a batch of related personalized messages into one approval. (The other live failure — *"không có quyền truy cập danh bạ tổ chức"* — was a delegated directory-read 403 in `resolve_user`, unrelated to merging, and deliberately untouched here.)

---

## What you get now

The agent personalizes by calling `send_teams_message` **once per distinct message**, and a new optional **`group` argument** lets it decide how those calls are confirmed:

- **Same non-empty `group` label** across calls → **one consolidated card** with a per-recipient breakdown and a single **"✅ Confirm & send all"** button. On confirm, each recipient gets *their own* message.
- **Omitted / distinct `group`** → **separate confirmation cards**, each individually reviewable and confirmable.
- **No `group` at all** → the original text-based safety net is preserved: identical-text cards still fold to one, distinct-text cards stay separate. So "remind everyone the same thing" still yields one card with zero behavior change.

The merge/separate decision is now the **agent's**, expressed explicitly, rather than an accident of string equality.

---

## Design

| File | Change |
|------|--------|
| [agent/tools.py](../src/eventbuddy/agent/tools.py) | `send_teams_message` gains `group: str = ""`; docstring rewritten (personalize via N calls; `group` folds calls into one confirmation); `group` threaded to the closure |
| [agent/wiring.py](../src/eventbuddy/agent/wiring.py) | `send_teams_message_fn` accepts/stores `group` in the pending payload; `coalesce_teams_dm_cards` keys on `group`-or-text and gains a **personalized-merge** path; `_perform_send` `teams_dm` renders **per-target `text`** with shared-text fallback; `personalized_dm_card` injected into the `coalesce_cards` lambda |
| [bot/cards/builders.py](../src/eventbuddy/bot/cards/builders.py) | new `personalized_dm_card(items, pending_id)` — consolidated per-recipient breakdown, single confirm button |

**Coalescing key.** Each `teams_dm` card's pending now contributes a key: `__group__:{label}` when the agent supplied a non-empty `group`, else `__text__:{text}` (the original default). Within a merged group:
- all texts identical → the original simple batch card (shared top-level `text`, targets without per-target text);
- texts differ → a merged pending whose **each target carries its own `text`**, rendered as `personalized_dm_card`.

Single-card groups and distinct groups pass through untouched and in place — that is how "keep them separate" is realized.

**Dispatch.** `_perform_send`'s `teams_dm` branch now renders `t.get("text") or payload["text"]` per target, so a personalized batch sends each recipient their own message while the same-message-to-many and legacy single-text shapes are unaffected.

---

## Decisions (confirmed with the user, 2026-06-16)

| Question | Decision |
|----------|----------|
| How does the agent express per-recipient messages? | **Multiple tool calls** (one per distinct message) — robust against MaaS models that already split per person; smaller change than a structured single-call list. |
| How does the agent control merge-vs-separate? | **A new optional `group` label.** Same label → consolidated card; omitted/distinct → separate cards. |
| Confirmation UX shape | **Agent decides per situation** — both the consolidated and separate shapes exist. |
| Default when `group` is omitted | **Preserve the text-based safety net** — identical text merges, distinct stays separate. No regression for models that ignore `group`. |
| Per-recipient storage | The pending's `targets` may carry a per-target `text`; the dispatcher prefers it, falls back to the shared `text`. **Additive — legacy pendings still resolve.** |

---

## Cross-cutting rules preserved

- **Security (rule 2).** The card still carries only `{action, pending_id}` — recipients and per-recipient messages live server-side in the pending store. `personalized_dm_card`'s button data is asserted to contain only `action`/`pending_id` (`test_personalized_dm_card_data_carries_only_opaque_token`). Re-auth on confirm (drafter==clicker + role floor `member`) is unchanged.
- **Graceful degradation.** The coalescer keeps its best-effort `try/except` — any pending-store hiccup returns the cards unchanged so card delivery never breaks. No Graph creds / not signed in still degrades at send time exactly as before.
- **No new surface.** No migration, no new Redis key, no config flag, no dependency. The pending payload only *gains* optional fields (`group`, per-target `text`).
- **Scope discipline.** Only the generic 1-1 `send_teams_message` flow changed; event-scoped `prepare_reminders` / `send_participant_reminders` keep their own channel-choice card.

---

## Tests (9 new; existing ones updated for the new arg)

- `test_same_group_distinct_messages_consolidate` — three labelled personalized calls fold into one card; each target keeps its own text; per-call pendings superseded.
- `test_distinct_messages_no_group_stay_separate` — distinct text, no label → three separate cards, pendings untouched.
- `test_distinct_group_labels_force_separate` — same text, two labels → two cards (agent chose to separate).
- `test_same_group_same_text_renders_simple_batch_card` — a shared group with identical text still uses the simple batch shape (no per-target text).
- `test_teams_dm_personalized_sends_per_target_text` / `test_teams_dm_per_target_text_falls_back_to_shared` — dispatch sends each target its own message, falling back to the shared text.
- `test_personalized_dm_card_shows_each_recipient_message` / `test_personalized_dm_card_data_carries_only_opaque_token` — the card renders the per-recipient breakdown and leaks no identity on the button.
- `test_send_teams_message_passes_group_label_through` — the `group` label reaches the closure verbatim.
- Updated: `test_generic_send_tools_registered_with_identity_absent` (arg set now `{recipients, message, group}`) and `test_send_teams_message_callable_by_member_and_delegates` (`group: ""` default).

---

## Operating notes & follow-ups

- **Manual smoke (plan step 7) pending** — in the Emulator / live: *"send each member the details of their own tasks"* → one consolidated card → confirm once → each person gets their own message; then *"send them separately so I can review each"* → separate cards; and verify "remind everyone the same thing" still yields one card.
- **Directory 403 unaddressed by design** — personalized sends still depend on `resolve_user`, which needs delegated directory-read scope. If sends 403, that's the pre-existing Entra directory-scope gap (delegated-Graph plan), not this work.
- **Model reliance on `group`** — the one behavioral uncertainty is whether the MaaS model reuses a label consistently. Mitigated: the no-`group` default degrades to today's reasonable behavior, and the docstring nudges toward a shared label for related personalized batches.
