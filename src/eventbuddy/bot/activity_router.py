from botbuilder.core import ActivityHandler, TurnContext


class EventBuddyBot(ActivityHandler):
    """Phase 0: echo. Phase 1 replaces on_message_activity with intent routing."""

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        await turn_context.send_activity(f"Echo: {turn_context.activity.text}")
