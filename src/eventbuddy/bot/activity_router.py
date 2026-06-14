from botbuilder.core import ActivityHandler, CardFactory, MessageFactory, TurnContext

from eventbuddy.agent.graph import build_agent_graph
from eventbuddy.agent.wiring import build_orchestrator
from eventbuddy.bot.turn_artifacts import begin_artifacts, end_artifacts


class EventBuddyBot(ActivityHandler):
    def __init__(self):
        orchestrator = build_orchestrator()
        self._graph = build_agent_graph(orchestrator)
        # HITL confirm loop (Impl 1): handles Adaptive Card `Action.Submit` clicks.
        self._confirm = getattr(orchestrator, "confirm_handler", None)

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        activity = turn_context.activity

        # An Adaptive Card `Action.Submit` arrives as a message with `activity.value` set —
        # route it to the confirm handler instead of the agent (it was authorized at prepare
        # time; recipients live server-side, not in the model's head).
        value = activity.value
        confirm = getattr(self, "_confirm", None)  # defensive: bot may be built via __new__
        if confirm is not None and isinstance(value, dict) and value.get("action"):
            await confirm.handle(turn_context)
            return

        user_id = activity.from_property.id if activity.from_property else "unknown"
        channel_id = activity.conversation.id if activity.conversation else None
        # `activity.timestamp` is the channel-set send-time (UTC) — Phase 1.9 keeps it
        # instead of discarding it, so the agent can reason about when messages were sent.
        artifacts, token = begin_artifacts()
        try:
            result = self._graph.invoke(
                {
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "text": activity.text or "",
                    "sent_at": activity.timestamp,
                }
            )
        finally:
            end_artifacts(token)

        reply = result.get("reply")
        if reply:
            await turn_context.send_activity(reply)
        # Any cards a tool/capability emitted this turn (e.g. the reminder channel-choice
        # card) are sent as attachments after the text reply.
        for card in artifacts.cards:
            await turn_context.send_activity(
                MessageFactory.attachment(CardFactory.adaptive_card(card))
            )
