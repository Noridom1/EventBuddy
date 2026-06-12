from botbuilder.core import ActivityHandler, TurnContext

from eventbuddy.agent.graph import build_agent_graph
from eventbuddy.agent.wiring import build_orchestrator


class EventBuddyBot(ActivityHandler):
    def __init__(self):
        self._graph = build_agent_graph(build_orchestrator())

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        activity = turn_context.activity
        user_id = activity.from_property.id if activity.from_property else "unknown"
        channel_id = activity.conversation.id if activity.conversation else None
        result = self._graph.invoke(
            {"user_id": user_id, "channel_id": channel_id, "text": activity.text or ""}
        )
        await turn_context.send_activity(result["reply"])
