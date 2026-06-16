from langchain_core.messages import HumanMessage

from eventbuddy.agent.formatting import render_markdown
from eventbuddy.agent.orchestrator import Orchestrator, _default_role
from eventbuddy.agent.pending import PendingActionStore
from eventbuddy.agent.roster_store import RosterStore
from eventbuddy.agent.session import SessionStore
from eventbuddy.bot.auth import ROLE_RANK
from eventbuddy.bot.cards.builders import confirm_card, reminder_channel_card
from eventbuddy.bot.cards.report_card import report_card
from eventbuddy.bot.confirm import ConfirmHandler
from eventbuddy.bot.turn_artifacts import emit_card
from eventbuddy.common.logging import get_logger
from eventbuddy.config import settings
from eventbuddy.data.redis import get_redis
from eventbuddy.domain.identity import CallerIdentity

log = get_logger("agent.wiring")


def _graph_creds() -> bool:
    """True when *some* Graph auth is configured, so the Graph-backed tools advertise + attempt
    their capability. Under delegated auth (Plan 13) this gate is open whenever an OAuth
    connection is set — the per-user 'is this caller signed in?' check happens at call time
    (`graph_for()` returns None and the call degrades to a clean message). Under the legacy
    app-only fallback it requires the client-credentials trio. Without either, prepare still
    works and cards still render — only the live *send/read* degrades."""
    from eventbuddy.integrations.graph.delegated import delegated_enabled
    if delegated_enabled():
        return True
    return bool(
        settings.graph_tenant_id and settings.graph_client_id and settings.graph_client_secret
    )


class GraphAuthUnavailable(RuntimeError):
    """Raised by `_default_graph()` when no Graph client can be built: delegated auth is on but
    the caller has no token in scope (not signed in), or no auth is configured at all. Call
    sites already wrap Graph use in try/except and degrade to a friendly message."""


def graph_for(*, sender=None):
    """The single Graph-client factory (Plan 13). **Delegated-first:** when an OAuth connection
    is configured *and* a delegated token is in scope (published to the request ContextVar by
    the runner / confirm handler / scheduler), build a client that acts **on behalf of the
    signed-in user** — every call bounded by that user's own access. With delegated configured
    but no token in scope (user not signed in / background host token unavailable), return None
    — we deliberately do NOT fall back to tenant-wide app credentials (the IT mandate). Only
    when no OAuth connection is configured at all do we use the legacy app-only client-
    credentials provider, preserving graceful degradation during rollout. Returns None when
    nothing is available; callers degrade."""
    from eventbuddy.integrations.graph.client import GraphClient
    from eventbuddy.integrations.graph.delegated import (
        StaticTokenProvider,
        current_graph_token,
        delegated_enabled,
        mark_signin_needed,
    )
    if delegated_enabled():
        token = current_graph_token()
        if token:
            return GraphClient(StaticTokenProvider(token), sender=sender, delegated=True)
        # Delegated configured but no token in scope → the caller isn't signed in. Flag it so the
        # activity router can auto-prompt sign-in (only fires when Graph was actually attempted).
        mark_signin_needed()
        return None
    if settings.graph_tenant_id and settings.graph_client_id and settings.graph_client_secret:
        from eventbuddy.integrations.graph.token import MsalTokenProvider
        return GraphClient(MsalTokenProvider(), sender=sender)
    return None


def _team_id_for(ev) -> str | None:
    """The Teams team id to use for a channel Graph call (Impl 3 — the "wide" tenant→team
    fix). Prefer the event's stored `teams_team_id`; fall back to the configured team id, then
    the tenant id for back-compat. `ev=None` yields just the configured fallback. Never returns
    the tenant id when the event already has its real team id."""
    return (
        getattr(ev, "teams_team_id", None)
        or settings.microsoft_team_id
        or settings.microsoft_app_tenant_id
        or None
    )


def _perform_send(*, graph, payload: dict, channel: str | None) -> tuple[bool, str]:
    """Pure dispatch for a confirmed HITL action: perform the Microsoft Graph send and return
    `(ok, summary)`. Module-level (not a closure) so it's unit-testable with a fake Graph.
    All mail/reminders send **individually** — never a shared To/CC (PII rule §11). Raises
    only on an actual Graph error; a known precondition miss returns `(False, message)`."""
    from eventbuddy.capabilities.reminders import ReminderService
    action = payload.get("type")
    recipients = payload.get("recipient_emails", [])
    event_name = payload.get("event_name") or "the event"
    if action == "remind" and channel == "teams":
        channel_id = payload.get("channel_id")
        if not channel_id:
            return False, "This event has no Teams channel to post to."
        # Use the event's real team id (carried on the payload), not the tenant id (Impl 3).
        team_id = payload.get("team_id") or _team_id_for(None)
        graph.send_channel_message(
            team_id, channel_id,
            f"⏰ Reminder: '{payload.get('task_name')}' for {event_name} is due soon.",
        )
        return True, "✅ Posted the reminder to the event channel."
    if action == "remind":  # outlook (default)
        svc = ReminderService(graph)
        for email in recipients:
            svc.remind_outlook(
                email=email, task_name=payload.get("task_name", "your task"),
                event_name=event_name,
            )
        return True, f"✅ Sent {len(recipients)} Outlook reminder(s)."
    if action == "mail":
        # Impl 4 — a participant-reminder mail can also be broadcast to the event channel
        # (the Teams choice on the channel-choice card). Note: that reaches *channel members*,
        # not the file's standalone addresses, so it's a "also nudge the channel" path.
        if channel == "teams":
            channel_id = payload.get("channel_id")
            if not channel_id:
                return False, "This event has no Teams channel to post to."
            team_id = payload.get("team_id") or _team_id_for(None)
            notice = payload.get("notice_text") or payload.get("subject", "")
            graph.send_channel_message(
                team_id, channel_id, f"📢 {payload.get('subject', 'Reminder')}\n\n{notice}",
            )
            return True, "✅ Posted the reminder to the event channel."
        for email in recipients:
            graph.send_mail(
                subject=payload.get("subject", ""),
                body_html=payload.get("body_html", ""), to=[email],
            )
        return True, f"✅ Sent the email to {len(recipients)} recipient(s)."
    if action == "teams_dm":
        # Generic 1-1 Teams message (event-independent). Recipients were resolved to directory
        # ids at prepare time; create-or-get each 1-1 chat and post the message. Accepts the
        # batch `targets` list; falls back to the legacy single-target shape for old pendings.
        targets = payload.get("targets")
        if not targets:
            tid = payload.get("target_user_id")
            targets = ([{"user_id": tid, "display": payload.get("target_display") or "them"}]
                       if tid else [])
        if not targets:
            return False, "I don't have a resolved recipient to message."
        # The model authors the message in Markdown; Teams chat renders a subset of HTML,
        # so convert and post as html (newlines/bold/bullets survive instead of collapsing).
        body_html = render_markdown(payload.get("text", ""))
        sent = []
        for t in targets:
            chat_id = graph.create_one_on_one_chat(t["user_id"])
            graph.send_chat_message(chat_id, body_html, content_type="html")
            sent.append(t.get("display") or "them")
        if len(sent) == 1:
            return True, f"✅ Sent the Teams message to {sent[0]}."
        return True, f"✅ Sent the Teams message to {len(sent)} people ({', '.join(sent)})."
    return False, "I don't know how to perform that action."


def _card_action_data(card: dict) -> dict:
    """The `Action.Submit` data dict of a confirm card (carries `action` + `pending_id`), or {}."""
    try:
        return card["actions"][0]["data"] or {}
    except (KeyError, IndexError, TypeError):
        return {}


def coalesce_teams_dm_cards(cards: list[dict], *, pending_store, confirm_card_fn) -> list[dict]:
    """Merge the turn's `teams_dm` confirm cards that share the same message text into ONE card
    per distinct message — so a model that (against instructions) calls `send_teams_message` once
    per person still yields a single confirmation card instead of a flood.

    The recipient list lives server-side in the pending store (rule 2 — never on the card button),
    so merging means: read each card's pending payload, union the `targets` (deduped by user id),
    store one merged pending, and emit one rebuilt card pointing at it (superseded pendings are
    popped to free them). Non-`teams_dm` cards, and a message that only produced one card, pass
    through untouched and in place. Best-effort: any store hiccup returns the cards unchanged so
    card delivery never breaks."""
    try:
        groups: dict[str, dict] = {}  # text -> {targets, pids, payload, first_card}
        order: list[str] = []
        plan: list[tuple[str, object]] = []  # ("pass", card) | ("dm", text)
        for card in cards:
            data = _card_action_data(card)
            pid = data.get("pending_id")
            payload = (pending_store.get(pid)
                       if data.get("action") == "teams_dm" and pid else None)
            if not payload or not payload.get("targets"):
                plan.append(("pass", card))
                continue
            text = payload.get("text", "")
            g = groups.get(text)
            if g is None:
                g = groups[text] = {"targets": [], "pids": [], "payload": payload,
                                    "first_card": card}
                order.append(text)
            seen_ids = {t["user_id"] for t in g["targets"]}
            for t in payload["targets"]:
                if t["user_id"] not in seen_ids:
                    seen_ids.add(t["user_id"])
                    g["targets"].append(t)
            g["pids"].append(pid)
            plan.append(("dm", text))

        if not any(len(g["pids"]) > 1 for g in groups.values()):
            return cards  # nothing to merge — leave the list (and pendings) exactly as-is

        final: dict[str, dict] = {}
        for text in order:
            g = groups[text]
            if len(g["pids"]) <= 1:
                final[text] = g["first_card"]
                continue
            merged = dict(g["payload"])
            merged["targets"] = g["targets"]
            merged["text"] = text
            new_pid = pending_store.put(merged)
            for pid in g["pids"]:
                pending_store.pop(pid)  # supersede the per-recipient pendings
            displays = [t["display"] for t in g["targets"]]
            title = (f"Send Teams message to {displays[0]}?" if len(displays) == 1
                     else f"Send Teams message to {len(displays)} people?")
            final[text] = confirm_card_fn(
                title=title, summary="A direct 1-1 Teams chat message.",
                pending_id=new_pid, action="teams_dm", recipients=displays, body=text)

        out, emitted = [], set()
        for kind, val in plan:
            if kind == "pass":
                out.append(val)
            elif val not in emitted:
                out.append(final[val])
                emitted.add(val)
        return out
    except Exception as e:  # noqa: BLE001 — coalescing is best-effort; never drop cards on error
        log.warning(f"teams_dm card coalescing failed ({type(e).__name__}: {e})")
        return cards


def _expand_aliases(values) -> list[str]:
    """Normalize email recipients for the generic send tools. Accepts a single string (split on
    commas/semicolons) or a list; trims blanks, dedupes (case-insensitive, order-preserving), and
    expands a bare corporate alias (no '@') to '{alias}@{corp_email_domain}' when that's
    configured. A bare alias with no configured domain is dropped (we can't address it)."""
    import re as _re
    if isinstance(values, str):
        values = _re.split(r"[,;]", values)
    domain = settings.corp_email_domain
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        v = (raw or "").strip()
        if not v:
            continue
        if "@" not in v:
            if not domain:
                continue
            v = f"{v}@{domain}"
        key = v.lower()
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


# --- Impl 4: participant-roster helpers (module-level → unit-testable) ----------------------

def _filter_emails_by_status(rows: list[dict], only_status: str) -> list[str]:
    """Select participant emails from the roster rows by the file's own status value. With no
    `only_status`, return every row's email. Otherwise keep rows whose status matches (case-
    insensitive substring either way) — the model passes a value it saw in the file breakdown
    (e.g. 'pending', 'no') to chase those who haven't registered."""
    want = (only_status or "").strip().lower()
    if not want:
        return [r["email"] for r in rows if r.get("email")]
    out = []
    for r in rows:
        if not r.get("email"):
            continue
        st = str(r.get("status", "")).strip().lower()
        if st and (st == want or want in st or st in want):
            out.append(r["email"])
    return out


def _summarize_roster(filename: str, reading, token: str) -> str:
    """A compact, bounded description of a read roster for the model to relay (counts + ≤3
    sample rows + the token) — never the full address list (window discipline)."""
    lines = [
        f"Read '{filename}': {reading.total_rows} row(s), "
        f"{len(reading.emails)} unique participant email address(es)."
    ]
    if reading.headers:
        lines.append(f"Columns: {', '.join(str(h) for h in reading.headers)}.")
    if reading.status_column:
        bd = ", ".join(f"{k}: {v}" for k, v in reading.status_breakdown.items())
        lines.append(
            f"The file has its own status column '{reading.status_column}' — {bd}. "
            "(This is the organizer's tracking, not EventBuddy registration.)"
        )
    sample = reading.rows[:3]
    if sample:
        lines.append("Sample:")
        for r in sample:
            bits = [r.get("email", "")]
            if r.get("name"):
                bits.append(f"name={r['name']}")
            if r.get("status"):
                bits.append(f"status={r['status']}")
            lines.append("  - " + ", ".join(bits))
    lines.append(f"\nfile_token: {token}")
    lines.append(
        "Describe this to the user and confirm who to contact, then call "
        "send_participant_reminders with this file_token (and only_status to limit who)."
    )
    return "\n".join(lines)


_ROSTER_EXTS = (".xlsx", ".csv", ".tsv")
_PARSE_EXTS = _ROSTER_EXTS + (".docx", ".pdf")
# Everything read_event_file can open (Impl 5): docs + images + plain text.
_READABLE_EXTS = _PARSE_EXTS + (
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".txt", ".md", ".text")


def _pick_roster_attachment(attachments: list[dict]) -> dict | None:
    """Choose the file to read: a spreadsheet/CSV first, then any other parseable doc."""
    for exts in (_ROSTER_EXTS, _PARSE_EXTS):
        for a in attachments:
            if (a.get("name") or "").lower().endswith(exts):
                return a
    return None


def _pick_readable_attachment(attachments: list[dict]) -> dict | None:
    """Choose an uploaded file for read_event_file: first one with a readable extension, else
    the first attachment (let the parser decide)."""
    for a in attachments:
        if (a.get("name") or "").lower().endswith(_READABLE_EXTS):
            return a
    return attachments[0] if attachments else None

# A DM-injected event snapshot competes with the user's own turns for the 4096-token DM
# window, so keep the cross-context read compact (Phase 1.9, Part B).
EVENT_CTX_BUDGET = 700


def _build_event_context_fn(transcript, summarizer):
    """The single guarded DM→event cross-context read (Phase 1.9, Part B). Owns all three
    security checks (cross-cutting rule 2 + one-directional privacy) in one place:

      1. event id is always the *server-resolved* focused event — never a tool argument;
      2. membership is verified server-side (non-member → empty, not an error);
      3. only the event thread's L3 summary + L2 transcript tail are read — never L1, and
         never the reverse direction (an event channel never reads a user's DM).

    Returns a compact, timestamped snapshot string, or "" on any miss (no focused event /
    no channel bound / not a member / nothing recorded) — graceful, consistent with the
    rest of the system."""
    from eventbuddy.agent.context import event_thread_id
    from eventbuddy.agent.transcript import sent_at_prefix

    def event_context_fn(*, user_id: str | None = None, identity=None,
                          event_id: str | None = None) -> str:
        if not event_id:
            return ""
        if identity is None and user_id:
            identity = CallerIdentity.of(teams_user_id=user_id)
        if identity is None or identity.is_empty():
            return ""
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.events import EventRepository
        from eventbuddy.data.repositories.members import MemberRepository
        try:
            with session_scope() as s:
                ev = EventRepository(s).get(event_id)
                if ev is None or ev.teams_channel_id is None:
                    return ""  # no shared thread to read
                if MemberRepository(s).get_by_identity(event_id, identity) is None:
                    return ""  # not a member — don't leak the shared conversation
                thread_id = event_thread_id(ev.teams_channel_id)
                event_name = ev.event_name
        except Exception as e:  # noqa: BLE001 — degrade gracefully, never break the turn
            log.warning(f"event context read failed ({type(e).__name__}: {e})")
            return ""

        summary = summarizer.get_summary(thread_id) if summarizer is not None else ""
        tail = (
            transcript.rehydrate(thread_id, budget=EVENT_CTX_BUDGET)
            if transcript is not None
            else []
        )
        if not summary and not tail:
            return ""

        parts = [f"Context from event '{event_name}':"]
        if summary:
            parts.append(summary)
        if tail:
            parts.append("\nRecent discussion:")
            for m in tail:
                role = "User" if isinstance(m, HumanMessage) else "Assistant"
                speaker = getattr(m, "name", None)
                who = f"{role} ({speaker})" if speaker else role
                parts.append(f"{sent_at_prefix(m)}{who}: {m.content}")
        return "\n".join(parts)

    return event_context_fn


def _build_channel_event_fn():
    """The channel-scope event resolver (Impl 3). In a channel the focused event is the one
    bound to that channel — resolve it and backfill its real Teams team id on first sight.
    Module-level + lazy session import so tests can redirect `session_scope` to sqlite (same
    pattern as `_build_event_context_fn`)."""
    def channel_event_fn(*, channel_id, team_id=None):
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.events import EventRepository
        try:
            with session_scope() as s:
                repo = EventRepository(s)
                ev = repo.by_channel(channel_id)
                if ev is None:
                    return None
                if team_id and not ev.teams_team_id:
                    repo.set_team_id(ev.event_id, team_id)  # backfill, idempotent
                return ev.event_id
        except Exception as e:  # noqa: BLE001 — never break the turn over a lookup
            log.warning(f"channel event resolve failed ({type(e).__name__}: {e})")
            return None

    return channel_event_fn


def _build_setup_event_fn(sync_members_fn=None):
    """The group/channel onboarding resolver. Binds THIS conversation to an event — resolving it
    by name, or creating it when new — enrolls the caller as host, and (Impl 18) enrolls **every**
    member of the group/channel by their corporate identity. Identity, conversation id, team id
    and scope are server-supplied (rule 2). Reuses the repositories directly so it does NOT create
    a second Teams channel; it binds the existing conversation (`Event.teams_channel_id` = the
    conversation id, the same key `by_channel` resolves). `sync_members_fn` is injected (the
    roster sync); None disables enroll-all (tests / no-Graph). Module-level + lazy `session_scope`
    import so tests can sqlite-redirect."""
    def setup_event_fn(*, name, user_id, channel_id, team_id=None, scope="group",
                       role="member", display_name=None, objective="",
                       aad_object_id=None, email=None):
        from sqlalchemy import select

        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.events import EventRepository
        from eventbuddy.data.repositories.members import MemberRepository
        from eventbuddy.domain.models import Event
        if scope not in ("group", "channel"):
            return ("This sets up a group or channel for an event. In a 1-1 chat, use "
                    "create_event instead.")
        if not channel_id:
            return "I can't tell which conversation this is — try again from the group."
        name = (name or "").strip()
        if not name:
            return "Tell me the event name, e.g. 'this is the group for Spring Hackathon'."
        try:
            with session_scope() as s:
                events = EventRepository(s)
                members = MemberRepository(s)
                bound = events.by_channel(channel_id)
                existing = s.scalar(select(Event).where(Event.event_name.ilike(f"%{name}%")))
                # Rebinding this conversation to a *different* event needs host/moderator (it's
                # disruptive); first-time setup of an unbound conversation is open to anyone (the
                # declarer becomes host). Idempotent when already bound to the same event.
                if bound is not None:
                    if existing is not None and existing.event_id == bound.event_id:
                        return f"This group is already set up for '{bound.event_name}'."
                    if ROLE_RANK.get(role, 0) < ROLE_RANK["moderator"]:
                        return (f"This group is already set up for '{bound.event_name}'. Ask a "
                                "host or moderator if it should be changed.")
                    bound.teams_channel_id = None  # free the unique binding before re-pointing it
                    s.flush()
                if existing is not None:
                    target_id, event_name, created = existing.event_id, existing.event_name, False
                else:
                    ev = events.create(event_name=name, host_user_id=user_id,
                                       objective=objective or None, status="ideation")
                    target_id, event_name, created = ev.event_id, name, True
                events.set_channel(target_id, channel_id)
                if team_id:
                    events.set_team_id(target_id, team_id)
                # Enroll the caller as host — store their AAD id + email too (Impl 18) so the
                # roster sync below (and DM lookups) recognize them as one row, never a duplicate.
                members.upsert_member(target_id, {
                    "teams_user_id": user_id, "aad_object_id": aad_object_id,
                    "email": email, "display_name": display_name, "role": "host",
                })
        except Exception as e:  # noqa: BLE001 — degrade gracefully, never break the turn
            log.warning(f"setup_event failed ({type(e).__name__}: {e})")
            return "I couldn't set this group up right now — please try again shortly."

        verb = "Created and set up" if created else "Set up"
        msg = (f"✅ {verb} '{event_name}' for this group — I'll track this conversation's "
               f"discussion for it, and you're set as host. (event id {target_id})")
        # Impl 18 — enroll the rest of the group's members by corporate identity. Best-effort and
        # additive; degrades to a sign-in nudge when the host isn't signed in to Graph.
        if sync_members_fn is not None:
            actor = CallerIdentity.of(
                teams_user_id=user_id, aad_object_id=aad_object_id, email=email)
            result = sync_members_fn(
                event_id=target_id, channel_id=channel_id, team_id=team_id,
                scope=scope, actor_identity=actor,
            )
            msg += " " + _summarize_member_sync(result, on_setup=True)
        return msg

    return setup_event_fn


def _summarize_member_sync(result: dict, *, on_setup: bool = False) -> str:
    """One-line, user-facing summary of a roster sync (Impl 18). `on_setup` softens the phrasing
    for the setup flow ('Enrolled N members from this group.'); otherwise it's the explicit
    'update members' phrasing. A degraded result relays its own message."""
    if not result or not result.get("ok"):
        return (result or {}).get("message", "I couldn't read the group's members just now.")
    added = result.get("added") or []
    if added:
        names = ", ".join(added[:8]) + ("…" if len(added) > 8 else "")
        return f"Enrolled {len(added)} member(s) from this group: {names}."
    if on_setup:
        return "Everyone in this group is already enrolled."
    return "No new members to add — everyone here is already enrolled."


def _build_member_autoenroll_fn():
    """Builds the auto-enroll closure (Impl 18). Upserts the posting user into the bound event's
    roster keyed by their **identity** (Bot Framework id + AAD id + email) — so a member already
    enrolled from the group's Graph roster (by AAD id / email, no BF id yet) gets their BF id
    backfilled onto that SAME row instead of a duplicate, and a brand-new poster is inserted once.
    Called best-effort per shared-conversation turn; the orchestrator swallows failures. Module-
    level + lazy `session_scope` import so tests can sqlite-redirect."""
    def member_autoenroll_fn(*, event_id, user_id, display_name=None,
                             aad_object_id=None, email=None):
        if not (event_id and user_id):
            return
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.members import MemberRepository
        with session_scope() as s:
            MemberRepository(s).upsert_member(event_id, {
                "teams_user_id": user_id, "aad_object_id": aad_object_id,
                "email": email, "display_name": display_name, "role": "member",
            })

    return member_autoenroll_fn


def _build_sync_members_fn(graph_factory=None):
    """Roster sync (Impl 18): scan the conversation's Graph members and enroll anyone not yet on
    the event. Group/personal → `/chats/{id}/members`; channel → `/teams/.../channels/.../members`.
    Diffs by identity and **upserts** the missing ones, keyed by AAD id + corporate email so each
    member is recognized across the group chat and their own 1-1 DM. The caller's own Graph-member
    row is merged with their existing (host) row via their Bot Framework id, so the host is never
    duplicated. Additive (never removes); non-AAD/guest members (no AAD id and no email) are
    skipped + counted (no silent caps). Returns a result dict — `{ok, added, already, skipped}` or
    `{ok: False, message}`. Degrades cleanly, never raises. `graph_factory` is injectable for
    tests; defaults to the per-caller delegated client."""
    graph_factory = graph_factory or graph_for

    def sync_members_fn(*, event_id, channel_id, team_id=None, scope="group",
                        actor_identity=None):
        if not event_id:
            return {"ok": False, "message": "No event is set up for this conversation yet."}
        if not _graph_creds():
            return {"ok": False,
                    "message": "I can't read the members yet — Microsoft Graph isn't configured."}
        graph = graph_factory()
        if graph is None:
            return {"ok": False,
                    "message": ("I need access to read this group's members — please sign in to "
                                "Microsoft 365 (type 'sign in') and ask again.")}
        try:
            if scope == "channel":
                if not (team_id and channel_id):
                    return {"ok": False, "message": (
                        "I can't read this channel's members yet — I haven't seen its Teams team "
                        "id. Post once in the channel and try again.")}
                graph_members = graph.list_channel_members(team_id, channel_id)
            else:
                if not channel_id:
                    return {"ok": False,
                            "message": "I can't tell which chat this is, so I can't read members."}
                graph_members = graph.list_chat_members(channel_id)
        except Exception as e:  # noqa: BLE001
            log.warning(f"member sync list failed ({type(e).__name__}: {e})")
            return {"ok": False,
                    "message": "I couldn't read the members right now — please try again shortly."}

        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.members import MemberRepository
        added: list[str] = []
        already = skipped = 0
        try:
            with session_scope() as s:
                repo = MemberRepository(s)
                for m in graph_members:
                    aad = m.get("id") or None
                    email = m.get("email") or None
                    name = m.get("display_name") or None
                    if not aad and not email:
                        skipped += 1  # non-AAD / guest — no stable corporate identity to key on
                        continue
                    fields = {"aad_object_id": aad, "email": email,
                              "display_name": name, "role": "member"}
                    # If this Graph member IS the caller, attach their Bot Framework id so the
                    # upsert merges with the host row they were enrolled under at setup.
                    if actor_identity is not None and (
                        actor_identity.matches_id(aad) or actor_identity.matches_email(email)
                    ) and actor_identity.teams_user_id:
                        fields["teams_user_id"] = actor_identity.teams_user_id
                    identity = CallerIdentity.of(
                        teams_user_id=fields.get("teams_user_id"),
                        aad_object_id=aad, email=email)
                    if repo.get_by_identity(event_id, identity) is None:
                        added.append(name or email or aad)
                    else:
                        already += 1
                    repo.upsert_member(event_id, fields)
        except Exception as e:  # noqa: BLE001
            log.warning(f"member sync upsert failed ({type(e).__name__}: {e})")
            return {"ok": False,
                    "message": "I couldn't update the members right now — please try again."}
        return {"ok": True, "added": added, "already": already, "skipped": skipped}

    return sync_members_fn


def _default_graph():
    """Back-compat default `graph_factory` for the tool closures: build a Graph client for the
    current caller (delegated) or app-only fallback, raising `GraphAuthUnavailable` when none
    is available so the existing per-call try/except degrades to a friendly message."""
    graph = graph_for()
    if graph is None:
        raise GraphAuthUnavailable(
            "No Graph auth available — sign in to Microsoft 365, or configure Graph creds."
        )
    return graph


def _default_chat_catalog():
    """Default per-chat file catalog (Impl 9) for the file-tool closures, shared by the list +
    read paths so a sync done by one is seen by the other."""
    from eventbuddy.capabilities.chat_files_catalog import ChatFileCatalog
    return ChatFileCatalog(vision_enabled=settings.llm_vision_enabled)


def _read_share_url(share_url: str):
    """Download a cataloged chat file by its share URL → `(filename, bytes)` or None. Uses the
    caller's delegated Graph client (`graph_for()`), the same path uploads take."""
    if not share_url:
        return None
    from eventbuddy.capabilities.attachments import fetch_attachment_bytes
    descriptor = {"name": "", "content_type": "", "download_url": None,
                  "content_url": share_url}
    needs_graph = share_url.startswith(("http://", "https://"))
    graph = graph_for() if needs_graph else None
    try:
        return fetch_attachment_bytes(descriptor, graph=graph)
    except Exception as e:  # noqa: BLE001
        log.warning(f"chat-file share-url read failed ({type(e).__name__}: {e})")
        return None


def _resolve_named_chat_file(catalog, *, channel_id, scope, attachments, query):
    """Resolve a file *name/description* against the chat catalog (Impl 9). Returns one of:
      ("bytes", (filename, content)) — a single confident match, downloaded;
      ("ambiguous", [rows])          — several candidates, caller disambiguates;
      ("none", message)              — nothing matched (message lists what's available).
    Runs a sync first so freshly-shared files are catalogued before matching."""
    graph = graph_for() if scope == "group" else None
    catalog.sync(channel_id, scope=scope, attachments=attachments or [], graph=graph)
    result = catalog.match(channel_id, query)
    if result.exact is not None:
        fetched = _read_share_url(result.exact.share_url)
        if fetched is None:
            return ("none", "I found that file but couldn't open it — please re-share it or "
                    "paste its SharePoint/OneDrive link.")
        return ("bytes", fetched)
    if result.candidates:
        return ("ambiguous", result.candidates)
    return ("none", None)  # caller composes the "no match" message (it can list the catalog)


def _chat_file_disambiguation(channel_id, query, candidates, *, pending_store=None):
    """Several catalog files match the query → ask the user which. Emits a dropdown picker card
    (Impl 9) when a pending store is available + an artifacts context is active, and always
    returns a text message listing the candidates so a plain-text reply ('the v4 one') works
    too. The model relays the message; the next turn resolves the narrowed name."""
    names = [c.filename for c in candidates]
    if pending_store is not None:
        try:
            from eventbuddy.bot.cards.builders import file_pick_card
            from eventbuddy.bot.turn_artifacts import emit_card
            pending_id = pending_store.put({
                "type": "read_files", "action": "read_files", "chat_id": channel_id,
                "query": query,
                "candidates": [
                    {"filename": c.filename, "share_url": c.share_url,
                     "drive_item_id": c.drive_item_id}
                    for c in candidates
                ],
            })
            emit_card(file_pick_card(query=query, names=names, pending_id=pending_id))
        except Exception as e:  # noqa: BLE001 — card is a nicety; the text below still works
            log.warning(f"file-pick card skipped ({type(e).__name__}: {e})")
    listing = "\n".join(f"• {n}" for n in names)
    return (f"I found a few files matching '{query}':\n{listing}\n"
            "Which one should I read? (pick from the list above, or tell me the exact name.)")


def _build_read_channel_fn(graph_factory=None):
    """The brainstorm channel read (Impl 3, Part 3). Reads the focused event channel's recent
    messages, membership-guarded, wrapping the result as untrusted external content. Degrades
    to a clean message (never raises). `graph_factory` is injectable for tests; defaults to a
    real Graph client. Module-level + lazy `session_scope` import so tests can sqlite-redirect."""
    graph_factory = graph_factory or _default_graph

    def read_channel_discussion_fn(*, user_id, event_id, limit=30):
        from eventbuddy.agent.tools import wrap_untrusted
        if not event_id:
            return ("Focus on the event whose channel you want me to read first "
                    "(e.g. 'focus on AI Workshop').")
        if not _graph_creds():
            return "I can't read channel messages yet — Microsoft Graph isn't configured."
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.events import EventRepository
        from eventbuddy.data.repositories.members import MemberRepository
        try:
            with session_scope() as s:
                ev = EventRepository(s).get(event_id)
                if ev is None:
                    return "I couldn't find that event anymore."
                team_id, channel_id, event_name = (
                    ev.teams_team_id, ev.teams_channel_id, ev.event_name)
                is_member = MemberRepository(s).get_by_user(event_id, user_id) is not None
                is_host = ev.host_user_id == user_id
        except Exception as e:  # noqa: BLE001
            log.warning(f"channel read prep failed ({type(e).__name__}: {e})")
            return "I couldn't read the channel right now — please try again shortly."
        if not channel_id:
            return "This event has no Teams channel bound, so there's no discussion to read."
        if not team_id:
            return ("I can't read this channel's messages yet — I haven't seen its Teams team "
                    "id. Post once in the channel and try again.")
        if not (is_member or is_host):
            return "You're not a member of this event, so I can't share its channel discussion."
        try:
            msgs = graph_factory().list_channel_messages(team_id, channel_id, limit)
        except Exception as e:  # noqa: BLE001
            log.warning(f"channel read failed ({type(e).__name__}: {e})")
            return "I couldn't read the channel right now — please try again shortly."
        if not msgs:
            return f"There are no recent messages in the channel for '{event_name}'."
        # Graph returns newest-first; show oldest-first so the discussion reads naturally.
        body = "\n".join(f"{m['author']}: {m['text']}" for m in reversed(msgs))
        return wrap_untrusted(f"Teams channel discussion for '{event_name}'", body)

    return read_channel_discussion_fn


def _build_list_members_fn(graph_factory=None):
    """List the people in the current conversation (Impl 8) — scope-aware and event-independent.
    A group chat / 1-1 DM resolves via `/chats/{chat-id}/members` (the chat id is the inbound
    `channel_id`); a Team channel resolves via `/teams/{team-id}/channels/{channel-id}/members`.
    Read-only; wraps the roster as untrusted. The caller is a participant by construction and
    acts under their own delegated token, so Graph enforces access — no DB membership check.
    Degrades to a clean message (never raises)."""
    graph_factory = graph_factory or _default_graph

    def list_members_fn(*, scope, channel_id, team_id=None, user_id=None, event_id=None):
        from eventbuddy.agent.tools import wrap_untrusted
        if not _graph_creds():
            return "I can't list members yet — Microsoft Graph isn't configured."
        if scope in ("group", "personal"):
            if not channel_id:
                return "I can't tell which chat this is, so I can't list its members."
            try:
                members = graph_factory().list_chat_members(channel_id)
            except Exception as e:  # noqa: BLE001
                log.warning(f"chat member list failed ({type(e).__name__}: {e})")
                return "I couldn't list this chat's members right now — please try again shortly."
            where = "this chat"
        else:  # channel
            if not (team_id and channel_id):
                return ("I can't list this channel's members yet — I haven't seen its Teams team "
                        "id. Post once in the channel and try again.")
            try:
                members = graph_factory().list_channel_members(team_id, channel_id)
            except Exception as e:  # noqa: BLE001
                log.warning(f"channel member list failed ({type(e).__name__}: {e})")
                return ("I couldn't list this channel's members right now — please try again "
                        "shortly.")
            where = "this channel"
        if not members:
            return f"I couldn't find anyone in {where}."
        lines = []
        for m in members:
            name = m.get("display_name") or "(unknown)"
            email = m.get("email")
            lines.append(f"• {name} <{email}>" if email else f"• {name}")
        return wrap_untrusted(f"members of {where}", "\n".join(lines))

    return list_members_fn


# --- Impl 5: generic file browse + on-demand read (membership-gated, read-only) ------------

READ_FILE_BUDGET = 6000  # chars of file content returned to the model (window discipline)


def _resolve_channel_access(event_id, user_id):
    """Shared guard for the file tools: resolve the focused event's channel + verify the
    caller is a member/host. Returns `(ok, payload)` — `payload` is an error string when
    `ok` is False, else a dict `{team_id, channel_id, event_name}`. Mirrors the read_channel
    guard chain; lazy `session_scope` import so tests can sqlite-redirect."""
    if not event_id:
        return False, ("Focus on the event whose files you want me to look at first "
                       "(e.g. 'focus on AI Workshop').")
    if not _graph_creds():
        return False, "I can't read files yet — Microsoft Graph isn't configured."
    from eventbuddy.data.db import session_scope
    from eventbuddy.data.repositories.events import EventRepository
    from eventbuddy.data.repositories.members import MemberRepository
    try:
        with session_scope() as s:
            ev = EventRepository(s).get(event_id)
            if ev is None:
                return False, "I couldn't find that event anymore."
            team_id, channel_id, event_name = (
                ev.teams_team_id, ev.teams_channel_id, ev.event_name)
            is_member = MemberRepository(s).get_by_user(event_id, user_id) is not None
            is_host = ev.host_user_id == user_id
    except Exception as e:  # noqa: BLE001
        log.warning(f"file access prep failed ({type(e).__name__}: {e})")
        return False, "I couldn't read the files right now — please try again shortly."
    if not channel_id:
        return False, "This event has no Teams channel bound, so there are no files to read."
    if not team_id:
        return False, ("I can't read this channel's files yet — I haven't seen its Teams team "
                       "id. Post once in the channel and try again.")
    if not (is_member or is_host):
        return False, "You're not a member of this event, so I can't share its files."
    return True, {"team_id": team_id, "channel_id": channel_id, "event_name": event_name}


def _build_list_event_files_fn(graph_factory=None, catalog=None):
    """List the files available in the current conversation (Impl 5 + Impl 8 + Impl 9). In a Team
    channel this is the focused event channel's SharePoint files, enriched with each file's stored
    catalog summary + doc_type, membership-gated. In a **group chat / 1-1 DM** it is the chat's
    own files from the `chat_files` catalog (Impl 9) — keyed on the chat id, **no focused event
    required**, with *real* stored summaries (no longer name+URL only). A group chat draws from a
    Graph message scan + current attachments; a 1-1 DM draws from attachments only (a bot DM has
    no Graph chat, so `/chats/{a:…}` is never called). Read-only; wraps the list as untrusted."""
    graph_factory = graph_factory or _default_graph
    catalog = catalog or _default_chat_catalog()

    def _list_chat_files(channel_id, scope, attachments):
        from eventbuddy.agent.tools import wrap_untrusted
        if not _graph_creds():
            return "I can't read files yet — Microsoft Graph isn't configured."
        if not channel_id:
            return "I can't tell which chat this is, so I can't list its files."
        # Personal scope (1-1 DM) has no Graph chat → discover from attachments only, never a
        # /chats/{a:…} scan. Group scope additionally scans the chat's messages via Graph.
        graph = graph_for() if scope == "group" else None
        rows = catalog.sync(channel_id, scope=scope, attachments=attachments or [], graph=graph)
        if not rows:
            if scope == "personal":
                return ("No files yet in this chat — share a file here (or paste a "
                        "SharePoint/OneDrive link) and I'll read it.")
            return "No files have been shared in this chat yet."
        lines = []
        for r in rows:
            label = f"• {r.filename}"
            if r.doc_type:
                label += f" — {r.doc_type}"
            if r.summary:
                label += f" — {r.summary}"
            lines.append(label)
        return wrap_untrusted("files shared in this chat", "\n".join(lines))

    def list_event_files_fn(*, user_id, event_id, scope="channel", channel_id=None,
                            attachments=None):
        from eventbuddy.agent.tools import wrap_untrusted
        if scope in ("group", "personal"):
            return _list_chat_files(channel_id, scope, attachments)
        ok, info = _resolve_channel_access(event_id, user_id)
        if not ok:
            return info
        # Catalog enrichment: drive_item_id -> (summary, doc_type) from prior ingestion.
        catalog: dict[str, tuple] = {}
        try:
            from eventbuddy.data.db import session_scope
            from eventbuddy.data.repositories.documents import DocumentRepository
            with session_scope() as s:
                for d in DocumentRepository(s).list(event_id):
                    if d.drive_item_id:
                        catalog[d.drive_item_id] = (d.summary, d.doc_type)
        except Exception as e:  # noqa: BLE001 — enrichment is best-effort
            log.warning(f"file catalog read failed ({type(e).__name__}: {e})")
        try:
            graph = graph_factory()
            drive_id, folder_id = graph.get_channel_files_folder(
                info["team_id"], info["channel_id"])
            children = graph.list_children(drive_id, folder_id)
        except Exception as e:  # noqa: BLE001
            log.warning(f"list files failed ({type(e).__name__}: {e})")
            return "I couldn't list the files right now — please try again shortly."
        lines = []
        for c in children:
            if c.get("folder") is not None:
                continue  # skip subfolders (flat listing for v1)
            name = c.get("name", "(unnamed)")
            summary, doc_type = catalog.get(c.get("id"), (None, None))
            label = f"• {name}"
            if doc_type:
                label += f" — {doc_type}"
            if summary:
                label += f" — {summary}"
            label += f" (id: {c.get('id')})"
            lines.append(label)
        if not lines:
            return f"There are no files in the channel for '{info['event_name']}' yet."
        body = "\n".join(lines)
        return wrap_untrusted(f"files in '{info['event_name']}'", body)

    return list_event_files_fn


def _build_read_event_file_fn(graph_factory=None, catalog=None, pending_store=None):
    """Read ONE file's content on demand (Impl 5 + Impl 9). In a Team channel, resolves a
    `file_id` against the focused event's channel folder. In a **group chat / 1-1 DM**, prefers
    a file the user just shared (`attachments`), else resolves a file by **name/description**
    against the chat catalog (Impl 9) — a non-URL `link` value is treated as that name. A pasted
    SharePoint/OneDrive `link` works anywhere. Downloads LIVE and returns its content: text via
    the parsers, images/image-PDFs via the vision model. Read-only; wraps + bounds the content."""
    graph_factory = graph_factory or _default_graph
    catalog = catalog or _default_chat_catalog()

    def read_event_file_fn(
        *, user_id, event_id, attachments=None, file_id="", link="",
        scope="channel", channel_id=None,
    ):
        from eventbuddy.agent.tools import wrap_untrusted
        from eventbuddy.ingestion.parsers import parse, render_pdf_first_page

        attachments = attachments or []
        link = (link or "").strip()
        link_is_url = link.startswith(("http://", "https://"))
        # A `link` that isn't a URL is the model naming a file (e.g. "participants.csv") — in a
        # chat we resolve that name against the catalog, not as a share URL.
        name_query = link if (link and not link_is_url) else ""

        item_id = None
        # 1) A file shared in THIS turn is the preferred source in every scope — read it
        #    directly (no Graph chat scan; share links resolve via the caller's token).
        if not file_id and not link_is_url and attachments:
            fetched = _download_uploaded_file(attachments)
            if isinstance(fetched, str):  # a degradation message
                return fetched
            filename, content = fetched
        # 2) Group chat / 1-1 DM, no current attachment: resolve by name/description (Impl 9).
        elif scope in ("group", "personal") and not link_is_url:
            if not _graph_creds():
                return "I can't read files yet — Microsoft Graph isn't configured."
            if not name_query:
                return ("Tell me which file to read — name it (e.g. 'the agenda'), share it "
                        "here, or paste its SharePoint/OneDrive link.")
            kind, payload = _resolve_named_chat_file(
                catalog, channel_id=channel_id, scope=scope,
                attachments=attachments, query=name_query)
            if kind == "bytes":
                filename, content = payload
            elif kind == "ambiguous":
                return _chat_file_disambiguation(
                    channel_id, name_query, payload, pending_store=pending_store)
            else:  # none
                return payload or (
                    f"I don't see a file matching '{name_query}' here — call list_event_files "
                    "to see what's been shared, or upload the file.")
        elif not file_id and not link:
            return ("Tell me which file to read — upload it here, use the id from "
                    "list_event_files, or paste a SharePoint/OneDrive link.")
        elif file_id:
            ok, info = _resolve_channel_access(event_id, user_id)
            if not ok:
                return info
            try:
                graph = graph_factory()
                drive_id, _folder_id = graph.get_channel_files_folder(
                    info["team_id"], info["channel_id"])
                item_id = file_id
                content, filename, _mime = graph.get_drive_item_content(drive_id, item_id)
            except Exception as e:  # noqa: BLE001
                log.warning(f"channel file read failed ({type(e).__name__}: {e})")
                return "I couldn't open that file right now — please try again shortly."
        else:
            if not _graph_creds():
                return "I can't open links yet — Microsoft Graph isn't configured."
            try:
                graph = graph_factory()
                drive_id, item_id = graph.resolve_share_url(link)
                content, filename, _mime = graph.get_drive_item_content(drive_id, item_id)
            except Exception as e:  # noqa: BLE001
                log.warning(f"share-link file read failed ({type(e).__name__}: {e})")
                return "I couldn't open that link — check it's a valid SharePoint/OneDrive link."

        parsed = parse(filename, content)
        if parsed.kind == "unsupported":
            return f"I can't read '{filename}' — it's not a format I can open."

        if parsed.kind in ("image", "image_pdf"):
            body, doc_type = _read_image_file(parsed, render_pdf_first_page), "image"
            if body is None:
                return ("I found the file but can't read images right now "
                        "(vision isn't configured).")
        else:
            body = (parsed.text or "").strip()
            if not body:
                return f"I read '{filename}' but it had no readable text."
            doc_type = None

        truncated = body[:READ_FILE_BUDGET]
        if len(body) > READ_FILE_BUDGET:
            truncated += "\n…(truncated)"

        # Lazily backfill the catalog summary/type for a known channel file.
        if item_id:
            _backfill_understanding(event_id, item_id, truncated, doc_type)
        return wrap_untrusted(f"file: {filename}", truncated)

    return read_event_file_fn


def _download_uploaded_file(attachments):
    """Download an uploaded chat attachment for read_event_file (Impl 5). Picks the first
    parseable file, then reuses the Impl 4 `fetch_attachment_bytes` helper — which handles a
    Teams `downloadUrl`, a `data:` URI, a localhost URL (all offline, no Graph), and a
    SharePoint share link (via Graph, when creds exist). Returns `(filename, bytes)` or a
    degradation string."""
    from eventbuddy.capabilities.attachments import fetch_attachment_bytes

    descriptor = _pick_readable_attachment(attachments)
    if descriptor is None:
        return "I don't see a file I can read in what you sent."
    # Offline sources (Teams downloadUrl, data: URI, localhost) need no Graph — only a remote
    # SharePoint/OneDrive share link does. Build a (delegated) client just for that case, so an
    # uploaded file still reads when the user isn't signed in. `graph_for()` returns None
    # gracefully (no raise) when no auth is available.
    content_url = descriptor.get("content_url") or ""
    needs_graph = not descriptor.get("download_url") and content_url.startswith(
        ("http://", "https://"))
    graph = graph_for() if needs_graph else None
    try:
        fetched = fetch_attachment_bytes(descriptor, graph=graph)
    except Exception as e:  # noqa: BLE001
        log.warning(f"uploaded file download failed ({type(e).__name__}: {e})")
        fetched = None
    if not fetched:
        return "I couldn't download that file — please re-send it or check the link."
    return fetched


def _read_image_file(parsed, render_pdf_first_page):
    """Vision read for an image / image-PDF ParsedDoc. Returns the description text, or None
    when vision is unavailable (caller emits a clean message)."""
    if not settings.llm_vision_enabled:
        return None
    image_bytes, mime = parsed.raw_bytes, parsed.mime
    if parsed.kind == "image_pdf":
        rendered = render_pdf_first_page(parsed.raw_bytes or b"")
        if rendered is None:
            return "(scanned PDF — I couldn't render it to read.)"
        image_bytes, mime = rendered
    if not image_bytes:
        return "(image — nothing to read.)"
    from eventbuddy.integrations.llm.client import LLMGateway
    try:
        return LLMGateway().describe_image(
            image_bytes, mime,
            "Describe this image in detail: what it shows and any text it contains.",
        )
    except Exception as e:  # noqa: BLE001
        log.warning(f"vision read failed ({type(e).__name__}: {e})")
        return "(image — I couldn't read it right now.)"


def _backfill_understanding(event_id, drive_item_id, body, doc_type):
    """Best-effort: store a catalog summary for a file read that wasn't ingested before."""
    try:
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.documents import DocumentRepository
        with session_scope() as s:
            repo = DocumentRepository(s)
            doc = repo.get_by_drive_item(drive_item_id)
            if doc is None or doc.summary:
                return  # unknown to the catalog, or already summarized — leave it
            repo.set_understanding(
                drive_item_id, summary=body[:300], doc_type=doc_type or doc.doc_type)
    except Exception as e:  # noqa: BLE001
        log.warning(f"catalog backfill skipped ({type(e).__name__}: {e})")


def build_orchestrator() -> Orchestrator:
    """Compose the production orchestrator. Phase 1.7 routes the conversation through an
    LLM tool-calling runner (create_react_agent + layered memory); the same capability
    closures remain the tool bodies (DRY). Without MaaS creds — or with agent_mode=regex —
    it degrades to the Phase 1 regex router. Live Microsoft actions still require Graph
    credentials; until then create-event persists locally."""
    session_store = SessionStore(get_redis())
    pending_store = PendingActionStore(get_redis(), ttl=settings.pending_action_ttl)
    roster_store = RosterStore(get_redis(), ttl=settings.pending_action_ttl)
    # Impl 9 — one per-chat file catalog shared by the list + read paths (a sync done by one is
    # seen by the other) and by capture-on-receive.
    chat_catalog = _default_chat_catalog()

    def provision_fn(**kw):
        # `host_aad_object_id` / `host_email` (Impl 18) ride in **kw straight to
        # ProvisioningService.create_event, which stores them on the host member row.
        from eventbuddy.capabilities.provisioning import ProvisioningService
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.events import EventRepository
        from eventbuddy.data.repositories.members import MemberRepository
        # graph_for() builds a client as the signed-in host (delegated) — the channel is created
        # under the host's own access. None (host not signed in / no creds) → ProvisioningService
        # persists the event locally and skips channel creation (graceful degradation).
        with session_scope() as s:
            svc = ProvisioningService(
                EventRepository(s), MemberRepository(s),
                graph_for(), team_id=_team_id_for(None),
            )
            ev = svc.create_event(**kw)
            s.flush()
            return type("E", (), {"event_id": ev.event_id})()

    def _score_event_match(query: str, name: str) -> int:
        """Rank how well `name` matches `query`. Higher is better; 0 means no match. Prefers
        exact > prefix > contiguous-substring > all-query-words-present (any order). The
        word-overlap tier is why "AI Summit" resolves "AI Innovation Summit 2026" even though
        it isn't a contiguous substring — the old `ilike('%query%')` missed that."""
        q, n = query.strip().lower(), name.lower()
        if not q:
            return 0
        if q == n:
            return 100
        if n.startswith(q):
            return 80
        if q in n:
            return 60
        q_words = [w for w in q.split() if w]
        if q_words and all(w in n for w in q_words):
            return 40
        return 0

    def resolve_event_fn(query: str, *, user_id: str | None = None,
                         identity=None) -> str | None:
        """Resolve an event-name fragment to an event_id (backs `set_focus_event`). When an
        identity (or `user_id`) is given, only the caller's own events (member or host, matched by
        identity — Impl 18) are considered — you can't focus an event you're not part of — and the
        best name match among them wins (ties broken newest-first). Falls back to a global
        best-match when the caller has no candidates, so non-DB/test paths still resolve."""
        if identity is None and user_id:
            identity = CallerIdentity.of(teams_user_id=user_id)
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.events import EventRepository
        with session_scope() as s:
            repo = EventRepository(s)
            candidates: list = []
            if identity is not None and not identity.is_empty():
                candidates = [ev for ev, _role in repo.list_for_identity(identity)]
            if not candidates:
                from sqlalchemy import select

                from eventbuddy.domain.models import Event
                candidates = list(s.scalars(
                    select(Event).order_by(Event.created_at.desc())
                ))
            best, best_score = None, 0
            for ev in candidates:  # candidates are newest-first, so ties keep the newest
                score = _score_event_match(query, ev.event_name)
                if score > best_score:
                    best, best_score = ev, score
            return best.event_id if best else None

    def remind_fn(*, event_id, user_id, raw=""):
        """Impl 1: *prepare* (don't send) — resolve recipients, stash a one-shot pending
        action, emit the channel-choice card. The real send happens only on confirm. Returns
        None on success (the tool/regex caller uses its default 'pick a channel' message), or
        a friendly string on a degraded path."""
        if not event_id:
            return None
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.events import EventRepository
        from eventbuddy.data.repositories.members import MemberRepository
        try:
            with session_scope() as s:
                ev = EventRepository(s).get(event_id)
                if ev is None:
                    return "I couldn't find that event anymore."
                recipients = [m.email for m in MemberRepository(s).list(event_id) if m.email]
                event_name, channel_id = ev.event_name, ev.teams_channel_id
                team_id = _team_id_for(ev)
        except Exception as e:  # noqa: BLE001
            log.warning(f"reminder prep failed ({type(e).__name__}: {e})")
            return "Reminders are temporarily unavailable — please try again."
        if not recipients:
            return "There's no one to remind for this event yet."
        task_name = (raw or "").strip() or "your tasks"
        payload = {
            "type": "remind", "event_id": event_id, "event_name": event_name,
            "channel_id": channel_id, "team_id": team_id, "requested_by": user_id,
            "task_name": task_name, "recipient_emails": recipients, "note": raw,
        }
        try:
            pending_id = pending_store.put(payload)
        except Exception as e:  # noqa: BLE001 — Redis down: emit nothing rather than a dead card
            log.warning(f"pending store unavailable ({type(e).__name__}: {e})")
            return "Reminders are temporarily unavailable — please try again."
        emit_card(reminder_channel_card(
            task_name=task_name, recipients=recipients, pending_id=pending_id
        ))
        return None

    def report_fn(*, event_id, user_id=None):
        """Impl 2: aggregate metrics + LLM summary + next-event suggestions, persist a Report,
        emit a read-only report card, and draft the manager-summary email behind a HITL confirm
        card (reuses the Impl 1 pending-action + confirm machinery). When a responses-workbook
        is configured, fetch fresh MS Forms responses first. Degrades to a friendly message on
        any failure — never raises into the agent loop."""
        if not event_id:
            return ("Focus on an event first (e.g. 'focus on AI Workshop'), then ask for "
                    "the report.")
        from eventbuddy.capabilities.forms_sync import FormsResponseSync
        from eventbuddy.capabilities.reporting import ReportingService
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.audit import AuditRepository
        from eventbuddy.data.repositories.events import EventRepository
        from eventbuddy.data.repositories.feedback import FeedbackRepository
        from eventbuddy.data.repositories.members import MemberRepository
        from eventbuddy.data.repositories.reports import ReportRepository
        from eventbuddy.domain.feedback import FeedbackAnalyzer
        from eventbuddy.integrations.llm.client import LLMGateway

        try:
            with session_scope() as s:
                ev = EventRepository(s).get(event_id)
                if ev is None:
                    return "I couldn't find that event anymore."
                event_name = ev.event_name
                channel_id = ev.teams_channel_id
                # Per-event workbook (Option 1) wins; fall back to the global setting.
                workbook_url = ev.feedback_workbook_url or settings.feedback_workbook_url
                members = MemberRepository(s).list(event_id)
                manager_emails = [
                    m.email for m in members
                    if m.email and m.role in ("host", "moderator")
                ] or [m.email for m in members if m.email][:1]
                feedback_repo = FeedbackRepository(s)
                llm = LLMGateway()
                # Fetch fresh Form responses from the responses workbook (the chosen path).
                graph = graph_for() if _graph_creds() else None
                if graph is not None:
                    try:
                        from eventbuddy.capabilities.forms_sync import discover_workbook
                        syncer = FormsResponseSync(graph, feedback_repo, FeedbackAnalyzer(llm))
                        if workbook_url:
                            syncer.sync(event_id=event_id, workbook_url=workbook_url)
                        elif channel_id:
                            # Option 2: best-effort discovery from the channel's SharePoint.
                            found = discover_workbook(
                                graph, _team_id_for(ev), channel_id)
                            if found:
                                syncer.sync_drive_item(
                                    event_id=event_id, drive_id=found[0], item_id=found[1])
                        s.flush()
                    except Exception as e:  # noqa: BLE001
                        log.warning(f"forms sync skipped ({type(e).__name__}: {e})")
                report = ReportingService(
                    MemberRepository(s), feedback_repo, ReportRepository(s), llm,
                ).generate(event_id=event_id)
                s.flush()
                metrics, summary = report.metrics_json, report.summary_md
                suggestions, report_id = report.suggestions_md, report.report_id
                AuditRepository(s).record(
                    event_id=event_id, actor_user_id=user_id, action="report",
                    tool_name="generate_report", payload={"report_id": report_id},
                    result="generated",
                )
        except Exception as e:  # noqa: BLE001 — LLM/DB down: degrade, don't crash the turn
            log.warning(f"report generation failed ({type(e).__name__}: {e})")
            return "I couldn't generate the report right now — please try again shortly."

        emit_card(report_card(metrics=metrics, summary_md=summary, suggestions_md=suggestions))

        # Draft the manager-summary email behind the HITL gate (nothing sends until confirmed).
        tail = "📊 Report ready — posted the card above."
        if manager_emails:
            body_html = (f"<h3>Report — {event_name}</h3><p><b>Summary</b><br>{summary}</p>"
                         f"<p><b>Suggestions</b><br>{suggestions}</p>")
            payload = {
                "type": "mail", "event_id": event_id, "event_name": event_name,
                "requested_by": user_id, "subject": f"[Report] {event_name}",
                "body_html": body_html, "recipient_emails": manager_emails,
            }
            try:
                pending_id = pending_store.put(payload)
                emit_card(confirm_card(
                    title=f"Email the report to the manager? ({len(manager_emails)})",
                    summary=f"Sends the summary + suggestions for '{event_name}'.",
                    pending_id=pending_id, action="mail",
                ))
                tail += " Confirm on the card to email the summary to the manager."
            except Exception as e:  # noqa: BLE001
                log.warning(f"report email draft skipped ({type(e).__name__}: {e})")
        return tail

    def query_tasks_fn(*, user_id=None, identity=None, event_id):
        if identity is None and user_id:
            identity = CallerIdentity.of(teams_user_id=user_id)
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.tasks import TaskRepository
        with session_scope() as s:
            repo = TaskRepository(s)
            # Scope to the focused event so switching focus changes the list. Without a focus
            # (event_id None), fall back to the caller's tasks across all their events. Matched by
            # identity (Impl 18) — assignee_id (BF/AAD id) or assignee_email (domain identity).
            tasks = (repo.by_assignee_identity(identity, event_id)
                     if identity is not None and not identity.is_empty() else [])
            if not tasks:
                return ("You have no assigned tasks in this event." if event_id
                        else "You have no assigned tasks.")
            return "Your tasks:\n" + "\n".join(f"- {t.task_name} ({t.status})" for t in tasks)

    def list_event_tasks_fn(*, event_id):
        """The whole task board for one event — every task with assignee + status, grouped by
        status — backing `list_event_tasks`. Read-only; the focused-event gate happens upstream."""
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.members import MemberRepository
        from eventbuddy.data.repositories.tasks import TaskRepository
        try:
            with session_scope() as s:
                tasks = TaskRepository(s).list(event_id)
                if not tasks:
                    return "This event has no tasks yet."
                # Resolve assignee display names once (id/email → name) for readable output.
                members = MemberRepository(s).list(event_id)
                by_id = {m.teams_user_id: m.display_name for m in members if m.teams_user_id}
                by_email = {m.email: m.display_name for m in members if m.email}

                def who(t):
                    name = by_id.get(t.assignee_id) or by_email.get(t.assignee_email)
                    return name or t.assignee_email or "unassigned"

                order = {"todo": 0, "in_progress": 1, "done": 2}
                label = {"todo": "To do", "in_progress": "In progress", "done": "Done"}
                tasks.sort(key=lambda t: (order.get(t.status, 9), t.task_name.lower()))
                lines = [f"Task board ({len(tasks)} task(s)):"]
                for t in tasks:
                    lines.append(
                        f"- {t.task_name} — {label.get(t.status, t.status)} (assignee: {who(t)})"
                    )
                return "\n".join(lines)
        except Exception as e:  # noqa: BLE001
            log.warning(f"list event tasks failed ({type(e).__name__}: {e})")
            return "I couldn't load the event's tasks right now — please try again."

    def update_task_fn(*, user_id=None, identity=None, role, event_id, task_query, status):
        """Direct (non-HITL) task status update. Member may update own tasks; moderator/host
        any. Resolves the task by name within the focused event. Ownership is matched by identity
        (Impl 18) — the task's `assignee_id` (BF/AAD id) or `assignee_email` (domain identity)."""
        if identity is None and user_id:
            identity = CallerIdentity.of(teams_user_id=user_id)
        valid = {"todo", "in_progress", "done"}
        if status not in valid:
            return f"Status must be one of: {', '.join(sorted(valid))}."
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.tasks import TaskRepository
        try:
            with session_scope() as s:
                repo = TaskRepository(s)
                matches = [
                    t for t in repo.list(event_id) if task_query.lower() in t.task_name.lower()
                ]
                if not matches:
                    return f"I couldn't find a task matching '{task_query}'."
                if len(matches) > 1:
                    return f"'{task_query}' matches multiple tasks — please be more specific."
                t = matches[0]
                is_mod = ROLE_RANK.get(role, 0) >= ROLE_RANK["moderator"]
                owns = identity is not None and (
                    identity.matches_id(t.assignee_id) or identity.matches_email(t.assignee_email))
                if not is_mod and not owns:
                    return "You can only update your own tasks (moderators can update any)."
                name = t.task_name
                repo.set_status(t.task_id, status)
                return f"Updated '{name}' → {status}."
        except Exception as e:  # noqa: BLE001
            log.warning(f"update_task failed ({type(e).__name__}: {e})")
            return "Couldn't update the task right now."

    def send_mail_fn(*, user_id, event_id, subject, body, recipients=None):
        """Impl 1: draft an Outlook mail behind a HITL confirm card (bulk/outward → §9/§11).
        Stashes a pending action + emits a confirm card; never sends here."""
        emails = list(recipients) if recipients else []
        event_name = None
        if not emails:
            if not event_id:
                return "I don't have any recipients — focus an event or give me addresses."
            from eventbuddy.data.db import session_scope
            from eventbuddy.data.repositories.events import EventRepository
            from eventbuddy.data.repositories.members import MemberRepository
            try:
                with session_scope() as s:
                    ev = EventRepository(s).get(event_id)
                    event_name = ev.event_name if ev else None
                    emails = [m.email for m in MemberRepository(s).list(event_id) if m.email]
            except Exception as e:  # noqa: BLE001
                log.warning(f"mail recipient load failed ({type(e).__name__}: {e})")
                return "Couldn't load the recipient list right now."
        if not emails:
            return "There are no members to email for this event yet."
        payload = {
            "type": "mail", "event_id": event_id, "event_name": event_name,
            "requested_by": user_id, "subject": subject,
            "body_html": render_markdown(body), "recipient_emails": emails,
        }
        try:
            pending_id = pending_store.put(payload)
        except Exception as e:  # noqa: BLE001
            log.warning(f"pending store unavailable ({type(e).__name__}: {e})")
            return "Mail confirmation is temporarily unavailable — please try again."
        emit_card(confirm_card(
            title=f"Send email: {subject}", summary=f"To {len(emails)} recipient(s).",
            pending_id=pending_id, action="mail", recipients=emails, body=body,
        ))
        return "Drafted the email — confirm on the card to send."

    def send_email_fn(*, user_id, subject, body, recipients):
        """Generic (event-independent) email: expand aliases → addresses, draft behind the HITL
        confirm card. Reuses the `type: "mail"` send path (per-recipient, §11). `min_role: member`
        lets any member confirm their own send (the confirm gate keys off this — see confirm.py)."""
        emails = _expand_aliases(recipients)
        if not emails:
            return ("I need at least one recipient — give me an email address, or an alias if a "
                    "corporate domain is configured.")
        payload = {
            "type": "mail", "event_id": None, "requested_by": user_id,
            "subject": subject, "body_html": render_markdown(body), "recipient_emails": emails,
            "min_role": "member",
        }
        try:
            pending_id = pending_store.put(payload)
        except Exception as e:  # noqa: BLE001
            log.warning(f"pending store unavailable ({type(e).__name__}: {e})")
            return "Mail confirmation is temporarily unavailable — please try again."
        emit_card(confirm_card(
            title=f"Send email: {subject}", summary=f"To {len(emails)} recipient(s).",
            pending_id=pending_id, action="mail", recipients=emails, body=body,
        ))
        return f"Drafted the email to {len(emails)} recipient(s) — confirm on the card to send."

    def send_teams_message_fn(*, user_id, recipients, message):
        """Generic (event-independent) 1-1 Teams message to one or more colleagues: resolve each
        recipient (corporate alias/email) to a directory user, then draft a SINGLE HITL confirm
        card covering the whole batch — the same `message` goes to each. The directory lookup
        acts on the caller's behalf (delegated Graph) and degrades cleanly. The sends (create
        chat + post, per recipient) happen on confirm."""
        # Normalize to a deduped list (case-insensitive, order-preserving) — the model may pass a
        # single string or a list; either way we want one card for the batch.
        raw = recipients if isinstance(recipients, list) else [recipients]
        names, seen = [], set()
        for r in raw:
            r = (r or "").strip()
            if r and r.lower() not in seen:
                seen.add(r.lower())
                names.append(r)
        if not names:
            return "Tell me who to message — a corporate alias (e.g. 'phucnlt2') or their email."
        if not (message or "").strip():
            return "Tell me what the message should say."
        if not _graph_creds():
            return "I can't send Teams messages yet — Microsoft Graph isn't configured."
        graph = graph_for()
        if graph is None:
            return ("I can't send Teams messages yet — please sign in to Microsoft 365 (type "
                    "'sign in') so I can send it on your behalf.")
        resolved, not_found = [], []
        for name in names:
            try:
                user = graph.resolve_user(name)
            except Exception as e:  # noqa: BLE001
                # A 403 is a tenant directory-access denial (not a per-recipient miss) — it'll hit
                # every lookup, so abort the whole batch with one clear message. Nothing is sent.
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status == 403:
                    from eventbuddy.integrations.graph.delegated import (
                        current_graph_token,
                        token_scopes,
                    )
                    granted = token_scopes(current_graph_token())
                    log.warning(
                        f"directory lookup denied (403) resolving '{name}' — the signed-in "
                        "user's Graph token can't read the directory. Scopes actually granted on "
                        f"this token: {granted!r}. The tenant likely blocks directory reads for "
                        "delegated callers; an Entra admin must allow it."
                    )
                    return ("I couldn't send it — I don't have permission to look people up in "
                            "your organisation's directory yet. Please ask an admin to grant "
                            "directory read access, then try again.")
                log.warning(f"user resolve failed ({type(e).__name__}: {e})")
                return ("I couldn't send it — the Teams directory is unreachable right now. "
                        "Please ask me to try again shortly.")
            if not user or not user.get("id"):
                not_found.append(name)
                continue
            resolved.append({
                "user_id": user["id"],
                "display": user.get("display_name") or user.get("upn") or name,
            })
        if not resolved:
            missing = ", ".join(not_found)
            return (f"I couldn't find {missing} in the directory — check the alias(es) or use "
                    "full email addresses.")
        payload = {
            "type": "teams_dm", "event_id": None, "requested_by": user_id,
            "targets": resolved, "text": message, "min_role": "member",
        }
        try:
            pending_id = pending_store.put(payload)
        except Exception as e:  # noqa: BLE001
            log.warning(f"pending store unavailable ({type(e).__name__}: {e})")
            return "Message confirmation is temporarily unavailable — please try again."
        displays = [t["display"] for t in resolved]
        title = (f"Send Teams message to {displays[0]}?" if len(displays) == 1
                 else f"Send Teams message to {len(displays)} people?")
        emit_card(confirm_card(
            title=title, summary="A direct 1-1 Teams chat message.",
            pending_id=pending_id, action="teams_dm", recipients=displays, body=message,
        ))
        reply = (f"Drafted a Teams message to {displays[0]} — confirm on the card to send."
                 if len(displays) == 1
                 else f"Drafted a Teams message to {len(displays)} recipient(s) — confirm on the "
                      "card to send.")
        if not_found:
            reply += f" (Couldn't find: {', '.join(not_found)}.)"
        return reply

    def ingest_fn(*, event_id, user_id, url=""):
        """Impl 2: pull the focused event's channel SharePoint files (or a pasted link)
        through the parse→structure→upsert pipeline, proposing invites via a HITL card posted
        to the channel. Degrades cleanly without Graph creds / a bound channel."""
        if not _graph_creds():
            return "I can't read files yet — Microsoft Graph isn't configured."
        from eventbuddy.capabilities.channel_files import ChannelFilesService
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.events import EventRepository
        from eventbuddy.ingestion.extractor import Extractor
        from eventbuddy.ingestion.pipeline import IngestionPipeline
        from eventbuddy.integrations.llm.client import LLMGateway

        graph = graph_for()
        if graph is None:
            return ("I can't read files yet — please sign in to Microsoft 365 so I can read "
                    "the channel's files on your behalf.")
        try:
            # Resolve the event's real team id + channel up front (Impl 3 — channel Graph
            # calls need the team id, not the tenant id).
            with session_scope() as s:
                ev = EventRepository(s).get(event_id)
                channel_id = ev.teams_channel_id if ev else None
                team_id = _team_id_for(ev) if ev else _team_id_for(None)

            def post_card(channel_id, card):
                graph.send_channel_card(team_id, channel_id, card)

            llm = LLMGateway()
            pipeline = IngestionPipeline(
                graph, Extractor(llm),
                pending_store=pending_store, post_card=post_card,
                llm=llm, vision=llm if settings.llm_vision_enabled else None,
            )
            svc = ChannelFilesService(graph, pipeline, team_id=team_id)
            if url:
                summary = svc.ingest_link(event_id=event_id, url=url)
            else:
                if not channel_id:
                    return "This event has no Teams channel bound, so I can't read its files."
                summary = svc.sync_channel(event_id=event_id, channel_id=channel_id)
        except Exception as e:  # noqa: BLE001
            log.warning(f"file ingestion failed ({type(e).__name__}: {e})")
            return "I couldn't read the files right now — please try again shortly."

        parts = [f"📎 Ingested {summary['files_ingested']} file(s)"]
        if summary["members_added"]:
            parts.append(f"added {summary['members_added']} member(s)")
        if summary["tasks_added"]:
            parts.append(f"found {summary['tasks_added']} task(s)")
        msg = ", ".join(parts) + "."
        if summary["invited_proposed"]:
            msg += (f" I posted a card to the channel to invite "
                    f"{summary['invited_proposed']} member(s) — confirm to send.")
        return msg

    def set_feedback_fn(*, event_id, form_url=None, workbook_url=None):
        """Impl 2: store the per-event feedback Form / responses-workbook links so each event
        (with its own SharePoint site) reads/sends from its own sources."""
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.events import EventRepository
        try:
            with session_scope() as s:
                EventRepository(s).set_feedback_sources(
                    event_id, form_url=form_url, workbook_url=workbook_url)
        except Exception as e:  # noqa: BLE001
            log.warning(f"set feedback sources failed ({type(e).__name__}: {e})")
            return "Couldn't save the feedback sources right now."
        bits = []
        if form_url:
            bits.append("feedback form link")
        if workbook_url:
            bits.append("responses workbook link")
        return f"Saved the {' and '.join(bits)} for this event."

    def read_participant_file_fn(*, user_id, event_id, attachments=None, link="",
                                 scope="personal", channel_id=None):
        """Impl 4 + Impl 9: read a participant-roster file — a file the user just shared, a
        SharePoint/OneDrive `link`, or (in a group chat / 1-1 DM) a file resolved by
        **name/description** against the chat catalog (a non-URL `link` is treated as that name).
        Extract the participant email addresses, stash the reading in the transient RosterStore,
        and return a bounded summary for the agent to relay + confirm. Stateless — the roster is
        never persisted to the DB and never becomes EventMembers."""
        from eventbuddy.agent.tools import wrap_untrusted
        from eventbuddy.capabilities.attachments import fetch_attachment_bytes
        from eventbuddy.ingestion.parsers import parse
        from eventbuddy.ingestion.roster import extract_roster

        attachments = attachments or []
        link = (link or "").strip()
        link_is_url = link.startswith(("http://", "https://"))
        name_query = link if (link and not link_is_url) else ""

        descriptor = _pick_roster_attachment(attachments)
        if descriptor is None and link_is_url:
            descriptor = {"name": "", "content_type": "", "download_url": None,
                          "content_url": link}
        fetched = None
        if descriptor is not None:
            graph = None
            content_url = descriptor.get("content_url") or ""
            # A remote SharePoint/OneDrive link needs Graph; an uploaded file (downloadUrl/data
            # URI) reads offline. `graph_for()` degrades to None when the user isn't signed in.
            if not descriptor.get("download_url") and content_url.startswith(
                    ("http://", "https://")):
                if not _graph_creds():
                    return ("I can't open that link — Microsoft Graph isn't configured. Upload "
                            "the file directly in the chat instead.")
                graph = graph_for()
                if graph is None:
                    return ("I can't open that link yet — please sign in to Microsoft 365 (type "
                            "'sign in'), or upload the file directly in the chat instead.")
            try:
                fetched = fetch_attachment_bytes(descriptor, graph=graph)
            except Exception as e:  # noqa: BLE001
                log.warning(f"participant file download failed ({type(e).__name__}: {e})")
                fetched = None
        elif scope in ("group", "personal") and name_query:
            # Resolve the roster by name/description against the chat catalog (Impl 9).
            if not _graph_creds():
                return "I can't read files yet — Microsoft Graph isn't configured."
            kind, payload = _resolve_named_chat_file(
                chat_catalog, channel_id=channel_id, scope=scope,
                attachments=attachments, query=name_query)
            if kind == "ambiguous":
                return _chat_file_disambiguation(
                    channel_id, name_query, payload, pending_store=pending_store)
            if kind == "none":
                return payload or (
                    f"I don't see a participant file matching '{name_query}' here — upload an "
                    ".xlsx/.csv list, or call list_event_files to see what's been shared.")
            fetched = payload  # ("bytes", (filename, content))
        else:
            return ("Upload a participant list (.xlsx or .csv) here, name the file you mean, or "
                    "paste a SharePoint/OneDrive share link, and I'll read it.")
        if not fetched:
            return "I couldn't download that file — please re-send it or check the link."
        filename, content = fetched
        parsed = parse(filename, content)
        if parsed.kind == "unsupported":
            return (f"I couldn't read '{filename or 'that file'}' — please send an .xlsx or "
                    ".csv participant list.")
        reading = extract_roster(parsed)
        if not reading.emails:
            return (f"I read '{filename}' but found no email addresses in it — make sure it has "
                    "a column with participant emails.")
        try:
            token = roster_store.put({**reading.to_dict(), "filename": filename})
        except Exception as e:  # noqa: BLE001 — Redis down: don't hand back a dead token
            log.warning(f"roster store unavailable ({type(e).__name__}: {e})")
            return "I read the file but can't stage it right now — please try again shortly."
        return wrap_untrusted(
            f"participant file: {filename}", _summarize_roster(filename, reading, token)
        )

    def send_participant_reminders_fn(*, user_id, event_id, subject, body, file_token,
                                      only_status=""):
        """Impl 4: resolve participant recipients from a previously-read roster (server-side,
        via `file_token`), stash a pending mail action, and emit the Teams-vs-Outlook channel-
        choice card. Nothing sends until the EO confirms. Recipients come from the transient
        roster stash — never the DB, never EventMembers."""
        if not file_token:
            return ("Read a participant file first with read_participant_file — then I'll have "
                    "a token to send to.")
        try:
            reading = roster_store.get(file_token)
        except Exception as e:  # noqa: BLE001
            log.warning(f"roster store unavailable ({type(e).__name__}: {e})")
            return "I can't reach the staged file right now — please try again shortly."
        if not reading:
            return ("That file reading expired or I don't have it — please re-send the "
                    "participant file and I'll read it again.")
        rows = reading.get("rows") or []
        emails = _filter_emails_by_status(rows, only_status) if only_status else (
            reading.get("emails") or [])
        emails = list(dict.fromkeys(e.lower() for e in emails if e))  # dedupe, keep order
        if not emails:
            return ("No participants matched that filter — check the status value, or leave it "
                    "empty to contact everyone in the file.")
        event_name = channel_id = team_id = None
        if event_id:
            from eventbuddy.data.db import session_scope
            from eventbuddy.data.repositories.events import EventRepository
            try:
                with session_scope() as s:
                    ev = EventRepository(s).get(event_id)
                    if ev is not None:
                        event_name, channel_id = ev.event_name, ev.teams_channel_id
                        team_id = _team_id_for(ev)
            except Exception as e:  # noqa: BLE001 — Outlook still works without event context
                log.warning(f"event lookup for participant send failed ({type(e).__name__}: {e})")
        payload = {
            "type": "mail", "event_id": event_id, "event_name": event_name,
            "requested_by": user_id, "subject": subject, "body_html": render_markdown(body),
            "recipient_emails": emails, "channel_id": channel_id, "team_id": team_id,
            "notice_text": body,
        }
        try:
            pending_id = pending_store.put(payload)
        except Exception as e:  # noqa: BLE001
            log.warning(f"pending store unavailable ({type(e).__name__}: {e})")
            return "Reminder confirmation is temporarily unavailable — please try again."
        emit_card(reminder_channel_card(
            task_name=subject, recipients=emails, pending_id=pending_id, body=body,
        ))
        return (f"Drafted a reminder to {len(emails)} participant(s) — choose Teams or Outlook "
                "on the card to send.")

    def list_events_fn(*, user_id=None, identity=None, current_event_id=None):
        """Impl 3 + Impl 18: list the caller's events (member or host) with status + role, marking
        the focused one. Read-only; scoped to the caller's own membership, matched by identity so
        an event the caller was enrolled into from a group roster (by AAD id / email) shows up in
        their DM."""
        if identity is None and user_id:
            identity = CallerIdentity.of(teams_user_id=user_id)
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.events import EventRepository
        try:
            with session_scope() as s:
                rows = (EventRepository(s).list_for_identity(identity)
                        if identity is not None and not identity.is_empty() else [])
                lines = []
                for ev, role in rows:
                    star = " ⭐ focused" if ev.event_id == current_event_id else ""
                    lines.append(f"• {ev.event_name} — {ev.status} (your role: {role}){star}")
        except Exception as e:  # noqa: BLE001
            log.warning(f"list events failed ({type(e).__name__}: {e})")
            return "I couldn't look up your events right now — please try again."
        if not lines:
            return "You're not part of any events yet."
        return "Your events:\n" + "\n".join(lines)

    def role_resolver(*, user_id, scope, channel_id, event_id=None, identity=None):
        """Membership-backed role (defense in depth). When an event is focused, the caller's
        real `EventMember.role` (matched by identity — Impl 18) overrides the DM-host default — so
        the in-tool moderator gate and the confirm re-auth reflect actual membership. Falls back
        to `_default_role` (host-in-DM) when there's no focused event yet (e.g. event creation). A
        **group chat** is exempt: it's a flat peer space, so we never downgrade a participant to
        their `EventMember.role` there — `_default_role` keeps everyone at moderator."""
        if scope == "group":
            return _default_role(
                user_id=user_id, scope=scope, channel_id=channel_id, event_id=event_id,
                identity=identity,
            )
        if identity is None and user_id:
            identity = CallerIdentity.of(teams_user_id=user_id)
        if event_id and identity is not None and not identity.is_empty():
            from eventbuddy.data.db import session_scope
            from eventbuddy.data.repositories.members import MemberRepository
            try:
                with session_scope() as s:
                    m = MemberRepository(s).get_by_identity(event_id, identity)
                    if m is not None:
                        return m.role
            except Exception as e:  # noqa: BLE001
                log.warning(f"role lookup failed ({type(e).__name__}: {e})")
        return _default_role(
            user_id=user_id, scope=scope, channel_id=channel_id, event_id=event_id,
            identity=identity,
        )

    def execute_confirmed_action(*, payload, channel, actor, authorized):
        """Side-effecting half of the HITL confirm loop: the real Graph send + every
        `audit_log` write (including denials/failures). Returns `(ok, reply_text)`. All
        outward mail/reminders send **individually** (PII rule §11), never a shared To/CC."""
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.audit import AuditRepository
        action = payload.get("type", "unknown")
        event_id = payload.get("event_id")

        def _audit(result):
            try:
                with session_scope() as s:
                    AuditRepository(s).record(
                        event_id=event_id, actor_user_id=actor, action=action,
                        tool_name=action, payload=payload, result=result,
                    )
            except Exception as e:  # noqa: BLE001
                log.warning(f"audit write failed ({type(e).__name__}: {e})")

        if not authorized:
            _audit("denied")
            return False, "You're not allowed to confirm this action."
        if not _graph_creds():
            _audit("failed")
            return False, "Couldn't send — Microsoft Graph isn't configured."

        graph = graph_for()
        if graph is None:
            _audit("failed")
            return False, ("Couldn't send — please sign in to Microsoft 365 so I can send this "
                           "on your behalf, then confirm again.")
        try:
            ok, summary = _perform_send(graph=graph, payload=payload, channel=channel)
        except Exception as e:  # noqa: BLE001
            log.warning(f"confirmed {action} send failed ({type(e).__name__}: {e})")
            _audit("failed")
            return False, "Couldn't send — the Microsoft Graph call failed."
        _audit("sent" if ok else "failed")
        return ok, summary

    # Agentic web tools (Impl 3) — only when Tavily is configured; otherwise the closures stay
    # None and the tools aren't registered (graceful degradation).
    web_search_fn = web_fetch_fn = None
    if settings.tavily_api_key:
        from eventbuddy.agent.tools import wrap_untrusted
        from eventbuddy.integrations.web.client import WebSearchClient
        web_client = WebSearchClient()

        def web_search_fn(*, query):
            results = web_client.search(query)
            if not results:
                return "No web results found (the search returned nothing or is unavailable)."
            body = "\n\n".join(
                f"[{i + 1}] {r['title']}\n{r['url']}\n{r['snippet']}"
                for i, r in enumerate(results)
            )
            return wrap_untrusted(f"web search: {query}", body)

        def web_fetch_fn(*, url):
            page = web_client.fetch(url)
            if not page or not page.get("content"):
                return f"Couldn't fetch readable content from {url}."
            return wrap_untrusted(f"web page: {url}", page["content"])

    def read_files_resolve(value: dict) -> dict:
        """Impl 9 — turn a file-picker `Action.Submit` into a synthesized user turn. Pops the
        one-shot pending payload (the candidate set + the original question), maps the selected
        file name(s) to share-link attachments, and returns `{text, attachments}` for the router
        to re-run through the agent (which then reads the file(s) and answers the original
        question, with that question still in the working window). Returns `{message}` on a
        degraded/expired path. Rule 2: the candidate set + question live server-side, never on
        the card."""
        from eventbuddy.bot.cards.builders import SHOW_ALL_CHOICE
        pending_id = value.get("pending_id")
        try:
            payload = pending_store.pop(pending_id) if pending_id else None
        except Exception as e:  # noqa: BLE001
            log.warning(f"pending store unavailable ({type(e).__name__}: {e})")
            payload = None
        if not payload or payload.get("type") != "read_files":
            return {"message": "That file picker expired — ask me to read the file again."}
        candidates = payload.get("candidates") or []
        query = payload.get("query") or "the file"
        selected = [s.strip() for s in str(value.get("selected") or "").split(",") if s.strip()]
        if SHOW_ALL_CHOICE in selected or not selected:
            # The picker only held the ambiguous subset; "show all" routes back through the
            # agent's own file listing so the user can pick from everything in the chat.
            return {"text": "List all the files shared in this chat so I can pick one.",
                    "attachments": []}
        chosen = [c for c in candidates if c.get("filename") in selected]
        if not chosen:
            return {"message": "I didn't catch which file you picked — please choose from the "
                               "list and submit again."}
        attachments = [{"name": c["filename"], "content_type": "reference",
                        "download_url": None, "content_url": c.get("share_url")}
                       for c in chosen]
        names = ", ".join(c["filename"] for c in chosen)
        text = (f"Read the file(s) I selected ({names}) and use them to answer my earlier "
                f"request about '{query}'.")
        return {"text": text, "attachments": attachments}

    sync_members_fn = _build_sync_members_fn()
    setup_event_fn = _build_setup_event_fn(sync_members_fn=sync_members_fn)
    member_autoenroll_fn = _build_member_autoenroll_fn()
    channel_event_fn = _build_channel_event_fn()
    runner, summarizer = _build_runner_and_summarizer(
        session_store, provision_fn, resolve_event_fn, remind_fn, report_fn, query_tasks_fn,
        update_task_fn, send_mail_fn, ingest_fn, set_feedback_fn,
        list_event_tasks_fn=list_event_tasks_fn,
        list_events_fn=list_events_fn, read_channel_fn=_build_read_channel_fn(),
        web_search_fn=web_search_fn, web_fetch_fn=web_fetch_fn,
        read_participant_file_fn=read_participant_file_fn,
        send_participant_reminders_fn=send_participant_reminders_fn,
        list_event_files_fn=_build_list_event_files_fn(catalog=chat_catalog),
        read_event_file_fn=_build_read_event_file_fn(
            catalog=chat_catalog, pending_store=pending_store),
        list_members_fn=_build_list_members_fn(),
        setup_event_fn=setup_event_fn,
        sync_members_fn=sync_members_fn,
        send_email_fn=send_email_fn, send_teams_message_fn=send_teams_message_fn,
    )

    orch = Orchestrator(
        session_store=session_store, provision_fn=provision_fn,
        resolve_event_fn=resolve_event_fn, remind_fn=remind_fn,
        report_fn=report_fn, query_tasks_fn=query_tasks_fn,
        runner=runner, agent_mode=settings.agent_mode if runner else "regex",
        role_resolver=role_resolver, channel_event_fn=channel_event_fn,
        member_autoenroll_fn=member_autoenroll_fn,
        capture_files_fn=lambda *, chat_id, attachments: chat_catalog.capture(
            chat_id, attachments),
        regex_fallback_on_error=not settings.agent_debug,
    )
    orch.summarizer = summarizer  # exposed so main.py can schedule the consolidation job
    # The activity router pulls this off the orchestrator to handle Adaptive Card clicks.
    orch.confirm_handler = ConfirmHandler(
        pending_store=pending_store, role_resolver=role_resolver,
        execute_fn=execute_confirmed_action,
    )
    # Impl 9 — the router calls this on a file-picker submit to synthesize a re-entry turn.
    orch.read_files_resolver = read_files_resolve
    # The router calls this on the turn's emitted cards before sending, to fold a flood of
    # per-recipient teams_dm cards into one (belt-and-suspenders over the batch tool).
    orch.coalesce_cards = lambda cards: coalesce_teams_dm_cards(
        cards, pending_store=pending_store, confirm_card_fn=confirm_card)
    return orch


def build_summarizer():
    """The rolling-summary consolidator, or None without MaaS creds. Stateless aside from
    its LLM/DB handles — safe to build standalone for the background scheduler job."""
    from eventbuddy.agent.summarizer import Summarizer
    from eventbuddy.integrations.llm.client import LLMGateway

    return Summarizer(LLMGateway()) if settings.agentbase_llm_base_url else None


def _build_runner_and_summarizer(
    session_store, provision_fn, resolve_event_fn, remind_fn, report_fn, query_tasks_fn,
    update_task_fn=None, send_mail_fn=None, ingest_fn=None, set_feedback_fn=None,
    list_event_tasks_fn=None,
    list_events_fn=None, read_channel_fn=None, web_search_fn=None, web_fetch_fn=None,
    read_participant_file_fn=None, send_participant_reminders_fn=None,
    list_event_files_fn=None, read_event_file_fn=None, setup_event_fn=None,
    send_email_fn=None, send_teams_message_fn=None, list_members_fn=None,
    sync_members_fn=None,
):
    """Build the LLM runner + summarizer, or (None, summarizer) when the chat path can't run
    (no creds / agent_mode=regex). The summarizer is built regardless so the background
    consolidation job can run wherever a transcript exists."""
    summarizer = build_summarizer()

    creds = bool(settings.agentbase_llm_base_url and settings.agentbase_llm_api_key)
    if settings.agent_mode != "llm" or not creds:
        if not creds:
            log.info("No MaaS creds — chat path degraded to the regex router.")
        return None, summarizer

    from eventbuddy.agent.memory import build_checkpointer, setup_checkpointer
    from eventbuddy.agent.model import build_chat_model, make_token_counter
    from eventbuddy.agent.runner import build_agent_runner
    from eventbuddy.agent.tools import AgentDeps, build_tools
    from eventbuddy.agent.transcript import Transcript

    model = build_chat_model()
    checkpointer = build_checkpointer()
    setup_checkpointer(checkpointer)
    transcript = Transcript()

    # Built here (after transcript + summarizer exist) so the cross-context closure can
    # close over them — same DRY composition-root pattern as the other capability closures.
    event_context_fn = _build_event_context_fn(transcript, summarizer)

    from eventbuddy.agent.tools import (
        _no_ingest,
        _no_list_event_files,
        _no_list_event_tasks,
        _no_list_events,
        _no_list_members,
        _no_read_channel,
        _no_read_event_file,
        _no_read_participant_file,
        _no_send_email,
        _no_send_mail,
        _no_send_participant_reminders,
        _no_send_teams_message,
        _no_set_feedback,
        _no_setup_event,
        _no_sync_members,
        _no_update_task,
    )

    deps = AgentDeps(
        session_store=session_store, provision_fn=provision_fn,
        resolve_event_fn=resolve_event_fn, remind_fn=remind_fn,
        report_fn=report_fn, query_tasks_fn=query_tasks_fn,
        event_context_fn=event_context_fn,
        update_task_fn=update_task_fn or _no_update_task,
        list_event_tasks_fn=list_event_tasks_fn or _no_list_event_tasks,
        send_mail_fn=send_mail_fn or _no_send_mail,
        ingest_fn=ingest_fn or _no_ingest,
        set_feedback_fn=set_feedback_fn or _no_set_feedback,
        list_events_fn=list_events_fn or _no_list_events,
        read_channel_fn=read_channel_fn or _no_read_channel,
        read_participant_file_fn=read_participant_file_fn or _no_read_participant_file,
        send_participant_reminders_fn=(
            send_participant_reminders_fn or _no_send_participant_reminders),
        list_event_files_fn=list_event_files_fn or _no_list_event_files,
        read_event_file_fn=read_event_file_fn or _no_read_event_file,
        list_members_fn=list_members_fn or _no_list_members,
        setup_event_fn=setup_event_fn or _no_setup_event,
        sync_members_fn=sync_members_fn or _no_sync_members,
        send_email_fn=send_email_fn or _no_send_email,
        send_teams_message_fn=send_teams_message_fn or _no_send_teams_message,
        web_search_fn=web_search_fn,
        web_fetch_fn=web_fetch_fn,
        debug=settings.agent_debug,
    )
    runner = build_agent_runner(
        model,
        tools_factory=lambda ctx: build_tools(deps, ctx),
        checkpointer=checkpointer,
        token_counter=make_token_counter(),
        transcript=transcript,
        summarizer=summarizer,
        debug=settings.agent_debug,
        trace=settings.agent_trace,
    )
    return runner, summarizer
