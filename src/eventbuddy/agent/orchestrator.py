import traceback
from datetime import datetime

from eventbuddy.agent.context import RequestContext, focus_key_for
from eventbuddy.agent.intents import Intent, classify
from eventbuddy.common.logging import get_logger

log = get_logger("agent.orchestrator")


def _default_role(*, user_id: str, scope: str, channel_id: str | None,
                  event_id: str | None = None) -> str:
    """Server-resolved caller role. In a 1-1 DM the user acts as the event leader (host);
    in a channel, default to member. Wiring may inject a membership-backed resolver that
    overrides this with the caller's real `EventMember.role` when an event is focused."""
    return "host" if scope == "personal" else "member"


class Orchestrator:
    """The agent brain. Phase 1.7: route the conversation through the LLM tool-calling
    runner, degrading to the Phase 1 regex router when the LLM is unavailable, errors, or
    when `agent_mode="regex"` forces the deterministic path. The `handle(...)` signature is
    stable so `activity_router.py` and `api/dev.py` don't change. Memory is owned by the
    runner's checkpointer — the orchestrator does not manage history."""

    def __init__(self, *, session_store, provision_fn, resolve_event_fn,
                 remind_fn, report_fn, query_tasks_fn,
                 runner=None, agent_mode: str = "llm", role_resolver=None,
                 channel_event_fn=None, regex_fallback_on_error: bool = True):
        self.session = session_store
        self.provision = provision_fn
        self.resolve_event = resolve_event_fn
        self.remind = remind_fn
        self.report = report_fn
        self.query_tasks = query_tasks_fn
        self.runner = runner
        self.agent_mode = agent_mode
        self._role_resolver = role_resolver or _default_role
        # Impl 3: in a channel, the focused event is the one bound to that channel (not the
        # caller's DM focus); this closure resolves it and backfills the real team id. None →
        # channel scope has no bound event (tests that build the orchestrator directly).
        self._channel_event_fn = channel_event_fn
        # Phase 1.8: when False, a *runtime* LLM error is surfaced (debug) instead of
        # degrading to regex. The no-creds path (runner is None / agent_mode=regex) is
        # decided at wiring time and is unaffected by this flag.
        self._regex_fallback_on_error = regex_fallback_on_error

    def _build_ctx(self, user_id: str, channel_id: str | None, scope: str,
                   sent_at: datetime | None, team_id: str | None = None,
                   attachments: list[dict] | None = None,
                   graph_token: str | None = None,
                   display_name: str | None = None) -> RequestContext:
        # In a channel the focused event is whatever is bound to this channel (and we backfill
        # its real team id on the way). Otherwise it comes from the session store, keyed per the
        # focus scope: shared across a group chat's members, private to the caller in a DM.
        if scope == "channel" and channel_id and self._channel_event_fn is not None:
            event_id = self._channel_event_fn(channel_id=channel_id, team_id=team_id)
        else:
            event_id = self.session.get_current_event(
                focus_key_for(scope, user_id, channel_id)
            )
        return RequestContext(
            user_id=user_id,
            channel_id=channel_id,
            scope=scope,
            role=self._role_resolver(
                user_id=user_id, scope=scope, channel_id=channel_id, event_id=event_id
            ),
            current_event_id=event_id,
            sent_at=sent_at,
            attachments=attachments or [],
            graph_token=graph_token,
            display_name=display_name,
        )

    @staticmethod
    def _with_attachment_note(text: str, attachments: list[dict]) -> str:
        """Surface attached file names to the model so it knows to read them (Impl 4). The
        note is server-built (rule 2) — the model can't fake an attachment, and the tool still
        re-derives the real file from `RequestContext.attachments`, not from this text."""
        if not attachments:
            return text
        names = ", ".join(a.get("name") or "a file" for a in attachments)
        note = (f"[The user attached the following file(s): {names}. If this is a participant "
                "roster, call read_participant_file to read it, then confirm who to contact.]")
        return f"{text}\n\n{note}" if text else note

    def handle(self, *, user_id: str, channel_id: str | None, text: str,
               scope: str = "personal", sent_at: datetime | None = None,
               team_id: str | None = None, attachments: list[dict] | None = None,
               graph_token: str | None = None, display_name: str | None = None) -> str:
        # `sent_at` (Phase 1.9), `team_id` (Impl 3), `attachments` (Impl 4), `graph_token`
        # (Plan 13 — delegated Graph auth) + `display_name` (group-chat speaker tagging) are
        # additive + keyword-defaulted so existing callers that don't pass them keep working.
        attachments = attachments or []
        if self.agent_mode == "llm" and self.runner is not None:
            try:
                ctx = self._build_ctx(user_id, channel_id, scope, sent_at, team_id, attachments,
                                      graph_token, display_name)
                return self.runner.run(self._with_attachment_note(text, attachments), ctx)
            except Exception as e:  # noqa: BLE001
                if not self._regex_fallback_on_error:
                    log.warning(f"LLM agent failed ({type(e).__name__}: {e}); surfacing (debug)")
                    return f"[agent error] {type(e).__name__}: {e}\n{traceback.format_exc()}"
                log.warning(f"LLM agent failed ({type(e).__name__}: {e}); falling back to regex")
        return self._regex_handle(user_id=user_id, channel_id=channel_id, text=text)

    def reset_dm(self, user_id: str) -> None:
        """Clear a user's 1-1 conversation memory + focused event (fresh start)."""
        if self.runner is not None and hasattr(self.runner, "reset"):
            self.runner.reset(f"dm:{user_id}")
        self.session.clear_current_event(user_id)

    def _regex_handle(self, *, user_id: str, channel_id: str | None, text: str) -> str:
        """Deterministic Phase 1 router — the graceful fallback when the LLM is unavailable."""
        c = classify(text)

        if c.intent == Intent.CREATE_EVENT:
            ev = self.provision(name=c.slots["event_name"], host_user_id=user_id,
                                member_emails=c.slots.get("emails", []))
            return f"✅ Created event '{c.slots['event_name']}' (id {ev.event_id})."

        if c.intent == Intent.CONTEXT_SWITCH:
            event_id = self.resolve_event(c.slots["event_query"])
            self.session.set_current_event(user_id, event_id)
            return f"🔒 Focused on '{c.slots['event_query']}'."

        if c.intent == Intent.REMIND:
            event_id = self.session.get_current_event(user_id)
            msg = self.remind(event_id=event_id, user_id=user_id, raw=c.slots.get("raw", ""))
            return msg or "I prepared the reminders — pick a channel on the card above."

        if c.intent == Intent.QUERY_TASKS:
            event_id = self.session.get_current_event(user_id)
            return self.query_tasks(user_id=user_id, event_id=event_id)

        if c.intent == Intent.GENERATE_REPORT:
            event_id = self.session.get_current_event(user_id)
            return self.report(event_id=event_id, user_id=user_id)

        return "Hi! Try: create event '<name>' members: a@x.com, or 'focus on <event>'."
