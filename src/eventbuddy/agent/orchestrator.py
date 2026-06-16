import traceback
from datetime import datetime

from eventbuddy.agent.context import RequestContext, focus_key_for
from eventbuddy.agent.intents import Intent, classify
from eventbuddy.common.logging import get_logger

log = get_logger("agent.orchestrator")


def _default_role(*, user_id: str, scope: str, channel_id: str | None,
                  event_id: str | None = None, identity=None) -> str:
    """Server-resolved caller role. In a 1-1 DM the user acts as the event leader (host).
    A group chat is a flat peer space — every participant resolves to `moderator`, so anyone
    can run the privileged actions (no host/moderator/member split in group scope). In a
    channel, default to member; wiring injects a membership-backed resolver that overrides
    this with the caller's real `EventMember.role` when an event is focused."""
    if scope == "personal":
        return "host"
    if scope == "group":
        return "moderator"
    return "member"


class Orchestrator:
    """The agent brain. Phase 1.7: route the conversation through the LLM tool-calling
    runner, degrading to the Phase 1 regex router when the LLM is unavailable, errors, or
    when `agent_mode="regex"` forces the deterministic path. The `handle(...)` signature is
    stable so `activity_router.py` and `api/dev.py` don't change. Memory is owned by the
    runner's checkpointer — the orchestrator does not manage history."""

    def __init__(self, *, session_store, provision_fn, resolve_event_fn,
                 remind_fn, report_fn, query_tasks_fn,
                 runner=None, agent_mode: str = "llm", role_resolver=None,
                 channel_event_fn=None, member_autoenroll_fn=None,
                 capture_files_fn=None,
                 regex_fallback_on_error: bool = True):
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
        # Group-chat onboarding: when a shared (group/channel) conversation is bound to an event,
        # enroll the posting user as an EventMember (keyed by Teams id) so they're recognized
        # here and in their own DM. Best-effort, server-side — None disables it (tests).
        self._member_autoenroll_fn = member_autoenroll_fn
        # Impl 9: capture file references shared in a group chat / 1-1 DM into the per-chat
        # catalog the moment they arrive — the share link rides only this activity and is lost
        # by the next turn (and a DM has no Graph chat to re-derive it). Best-effort; None
        # disables it (tests). Summaries are still backfilled lazily on a later list/read.
        self._capture_files_fn = capture_files_fn
        # Phase 1.8: when False, a *runtime* LLM error is surfaced (debug) instead of
        # degrading to regex. The no-creds path (runner is None / agent_mode=regex) is
        # decided at wiring time and is unaffected by this flag.
        self._regex_fallback_on_error = regex_fallback_on_error

    def _build_ctx(self, user_id: str, channel_id: str | None, scope: str,
                   sent_at: datetime | None, team_id: str | None = None,
                   attachments: list[dict] | None = None,
                   graph_token: str | None = None,
                   display_name: str | None = None,
                   aad_object_id: str | None = None,
                   user_email: str | None = None) -> RequestContext:
        # In a shared conversation (a Team channel *or* a group chat) the focused event is the one
        # bound to this conversation id — resolve it via the binding (and backfill the real team
        # id on the way, a no-op in a group chat where team_id is None). In a 1-1 DM the focus
        # comes from the session store, keyed to the caller.
        if scope in ("channel", "group") and channel_id and self._channel_event_fn is not None:
            event_id = self._channel_event_fn(channel_id=channel_id, team_id=team_id)
        else:
            event_id = self.session.get_current_event(
                focus_key_for(scope, user_id, channel_id)
            )
        ctx = RequestContext(
            user_id=user_id,
            aad_object_id=aad_object_id,
            user_email=user_email,
            channel_id=channel_id,
            scope=scope,
            team_id=team_id,
            role="member",  # provisional — resolved below now that the identity exists
            current_event_id=event_id,
            sent_at=sent_at,
            attachments=attachments or [],
            graph_token=graph_token,
            display_name=display_name,
        )
        # Role resolution matches the caller by their full identity (Impl 18) — so a member
        # enrolled by AAD id / email (not the BF id) gets their real stored role in a DM.
        ctx.role = self._role_resolver(
            user_id=user_id, scope=scope, channel_id=channel_id, event_id=event_id,
            identity=ctx.identity,
        )
        return ctx

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
               graph_token: str | None = None, display_name: str | None = None,
               aad_object_id: str | None = None, user_email: str | None = None) -> str:
        # `sent_at` (Phase 1.9), `team_id` (Impl 3), `attachments` (Impl 4), `graph_token`
        # (Plan 13 — delegated Graph auth), `display_name` (group-chat speaker tagging) and
        # `aad_object_id`/`user_email` (Impl 18 — cross-context identity) are additive +
        # keyword-defaulted so existing callers that don't pass them keep working.
        attachments = attachments or []
        self._maybe_capture_files(scope, channel_id, attachments)
        if self.agent_mode == "llm" and self.runner is not None:
            try:
                ctx = self._build_ctx(user_id, channel_id, scope, sent_at, team_id, attachments,
                                      graph_token, display_name, aad_object_id, user_email)
                self._maybe_autoenroll(ctx)
                return self.runner.run(self._with_attachment_note(text, attachments), ctx)
            except Exception as e:  # noqa: BLE001
                if not self._regex_fallback_on_error:
                    log.warning(f"LLM agent failed ({type(e).__name__}: {e}); surfacing (debug)")
                    return f"[agent error] {type(e).__name__}: {e}\n{traceback.format_exc()}"
                log.warning(f"LLM agent failed ({type(e).__name__}: {e}); falling back to regex")
        return self._regex_handle(user_id=user_id, channel_id=channel_id, text=text)

    def _maybe_capture_files(self, scope: str, channel_id: str | None,
                             attachments: list[dict]) -> None:
        """Record any files shared this turn into the per-chat catalog (Impl 9) — only in a
        group chat / 1-1 DM (a channel's files live in SharePoint, handled by ingestion). Cheap
        reference upsert; best-effort, never breaks the turn."""
        if (self._capture_files_fn is None or not attachments
                or scope not in ("group", "personal") or not channel_id):
            return
        try:
            self._capture_files_fn(chat_id=channel_id, attachments=attachments)
        except Exception as e:  # noqa: BLE001 — capture is best-effort
            log.warning(f"file capture skipped ({type(e).__name__}: {e})")

    def _maybe_autoenroll(self, ctx: RequestContext) -> None:
        """In a bound shared conversation, enroll the posting user as an EventMember (keyed by
        Teams id) so they're recognized here and in their own DM. Best-effort — a failure here
        must never break the turn."""
        if self._member_autoenroll_fn is None:
            return
        if ctx.scope not in ("group", "channel") or not ctx.current_event_id:
            return
        try:
            self._member_autoenroll_fn(
                event_id=ctx.current_event_id, user_id=ctx.user_id,
                display_name=ctx.display_name,
                aad_object_id=ctx.aad_object_id, email=ctx.user_email,
            )
        except Exception as e:  # noqa: BLE001 — enrollment is best-effort, never fatal
            log.warning(f"member auto-enroll skipped ({type(e).__name__}: {e})")

    def reset_dm(self, user_id: str) -> None:
        """Clear a user's 1-1 conversation memory + focused event (fresh start)."""
        if self.runner is not None and hasattr(self.runner, "reset"):
            self.runner.reset(f"dm:{user_id}")
        self.session.clear_current_event(user_id)

    def reset_all(self) -> dict:
        """Clear EVERY user's conversation context: all working windows, the durable transcript,
        all rolling summaries, and every focused-event session. Dev/demo only — wipes everyone so
        a fresh demo starts from a clean slate. Returns the per-layer counts cleared."""
        result: dict = {}
        if self.runner is not None and hasattr(self.runner, "reset_all"):
            result.update(self.runner.reset_all())
        else:
            # Degraded/regex path: no runner, but a summarizer may still exist (built regardless).
            summ = getattr(self, "summarizer", None)
            if summ is not None and hasattr(summ, "clear_all"):
                result["summaries"] = summ.clear_all()
        clear_sessions = getattr(self.session, "clear_all", None)
        if clear_sessions is not None:
            result["sessions"] = clear_sessions()
        log.info(f"reset_all cleared {result}")
        return result

    def _regex_handle(self, *, user_id: str, channel_id: str | None, text: str) -> str:
        """Deterministic Phase 1 router — the graceful fallback when the LLM is unavailable."""
        c = classify(text)

        if c.intent == Intent.CREATE_EVENT:
            ev = self.provision(name=c.slots["event_name"], host_user_id=user_id,
                                member_emails=c.slots.get("emails", []))
            return f"✅ Created event '{c.slots['event_name']}' (id {ev.event_id})."

        if c.intent == Intent.CONTEXT_SWITCH:
            event_id = self.resolve_event(c.slots["event_query"], user_id=user_id)
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
