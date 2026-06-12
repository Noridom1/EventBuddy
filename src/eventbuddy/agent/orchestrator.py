from eventbuddy.agent.context import RequestContext
from eventbuddy.agent.intents import Intent, classify
from eventbuddy.common.logging import get_logger

log = get_logger("agent.orchestrator")


def _default_role(*, user_id: str, scope: str, channel_id: str | None) -> str:
    """Server-resolved caller role. In a 1-1 DM the user acts as the event leader (host);
    in a channel, default to member. Wiring may inject a membership-backed resolver."""
    return "host" if scope == "personal" else "member"


class Orchestrator:
    """The agent brain. Phase 1.7: route the conversation through the LLM tool-calling
    runner, degrading to the Phase 1 regex router when the LLM is unavailable, errors, or
    when `agent_mode="regex"` forces the deterministic path. The `handle(...)` signature is
    stable so `activity_router.py` and `api/dev.py` don't change. Memory is owned by the
    runner's checkpointer — the orchestrator does not manage history."""

    def __init__(self, *, session_store, provision_fn, resolve_event_fn,
                 remind_fn, report_fn, query_tasks_fn,
                 runner=None, agent_mode: str = "llm", role_resolver=None):
        self.session = session_store
        self.provision = provision_fn
        self.resolve_event = resolve_event_fn
        self.remind = remind_fn
        self.report = report_fn
        self.query_tasks = query_tasks_fn
        self.runner = runner
        self.agent_mode = agent_mode
        self._role_resolver = role_resolver or _default_role

    def _build_ctx(self, user_id: str, channel_id: str | None, scope: str) -> RequestContext:
        return RequestContext(
            user_id=user_id,
            channel_id=channel_id,
            scope=scope,
            role=self._role_resolver(user_id=user_id, scope=scope, channel_id=channel_id),
            current_event_id=self.session.get_current_event(user_id),
        )

    def handle(self, *, user_id: str, channel_id: str | None, text: str,
               scope: str = "personal") -> str:
        if self.agent_mode == "llm" and self.runner is not None:
            try:
                ctx = self._build_ctx(user_id, channel_id, scope)
                return self.runner.run(text, ctx)
            except Exception as e:  # noqa: BLE001
                log.warning(f"LLM agent failed ({type(e).__name__}: {e}); falling back to regex")
        return self._regex_handle(user_id=user_id, channel_id=channel_id, text=text)

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
            self.remind(event_id=event_id, user_id=user_id, raw=c.slots.get("raw", ""))
            return "I prepared the reminders — pick a channel on the card above."

        if c.intent == Intent.QUERY_TASKS:
            event_id = self.session.get_current_event(user_id)
            return self.query_tasks(user_id=user_id, event_id=event_id)

        if c.intent == Intent.GENERATE_REPORT:
            event_id = self.session.get_current_event(user_id)
            return self.report(event_id=event_id)

        return "Hi! Try: create event '<name>' members: a@x.com, or 'focus on <event>'."
