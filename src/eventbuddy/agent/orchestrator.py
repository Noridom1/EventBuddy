from eventbuddy.agent.intents import Intent, classify


class Orchestrator:
    """The agent brain: classify → route to a capability → compose reply.
    Capabilities are injected as callables so this stays unit-testable and is the
    logic wrapped by the LangGraph graph in graph.py."""

    def __init__(self, *, session_store, provision_fn, resolve_event_fn,
                 remind_fn, report_fn, query_tasks_fn):
        self.session = session_store
        self.provision = provision_fn
        self.resolve_event = resolve_event_fn
        self.remind = remind_fn
        self.report = report_fn
        self.query_tasks = query_tasks_fn

    def handle(self, *, user_id: str, channel_id: str | None, text: str) -> str:
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
