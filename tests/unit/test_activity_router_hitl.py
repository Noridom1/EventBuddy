"""Activity-router HITL wiring (Impl 1): cards emitted during a turn go out as attachments,
and a card `Action.Submit` (activity.value) is routed to the confirm handler, bypassing the
agent. Uses a fake TurnContext — no Bot Framework adapter, no DB."""
import asyncio

from botbuilder.schema import Activity, ActivityTypes

from eventbuddy.bot.activity_router import EventBuddyBot
from eventbuddy.bot.turn_artifacts import emit_card


def _replies(sent):
    """Drop the Plan 14 typing-indicator activities — they're best-effort decoration sent on
    every turn and aren't part of the reply sequence under test."""
    return [
        a for a in sent
        if not (isinstance(a, Activity) and a.type == ActivityTypes.typing)
    ]


class _Activity:
    def __init__(self, text="", value=None):
        self.text = text
        self.value = value
        self.from_property = type("F", (), {"id": "u1", "name": "User One"})()
        self.conversation = type(
            "C", (), {"id": "c1", "is_group": False, "conversation_type": "personal"}
        )()
        self.timestamp = None


class _TurnContext:
    def __init__(self, activity):
        self.activity = activity
        self.sent = []

    async def send_activity(self, a):
        self.sent.append(a)


def test_emitted_card_is_sent_as_attachment_after_reply():
    bot = EventBuddyBot.__new__(EventBuddyBot)

    def invoke(_state):
        emit_card({"type": "AdaptiveCard", "id": "r1"})  # a tool/closure emitting mid-turn
        return {"reply": "prepared"}

    bot._graph = type("G", (), {"invoke": lambda self, s: invoke(s)})()
    bot._confirm = None
    tc = _TurnContext(_Activity(text="remind everyone"))

    asyncio.run(bot.on_message_activity(tc))

    replies = _replies(tc.sent)
    assert replies[0] == "prepared"  # text reply first
    attachments = replies[1].attachments  # then the card
    assert attachments[0].content == {"type": "AdaptiveCard", "id": "r1"}


def test_card_submit_routes_to_confirm_and_skips_agent():
    calls = []

    class _Confirm:
        async def handle(self, turn_context):
            calls.append(turn_context.activity.value)

    def _must_not_run(self, state):
        raise AssertionError("agent graph ran for a confirm click")

    bot = EventBuddyBot.__new__(EventBuddyBot)
    bot._confirm = _Confirm()
    bot._graph = type("G", (), {"invoke": _must_not_run})()  # must NOT run on a confirm click
    tc = _TurnContext(_Activity(value={"action": "remind", "pending_id": "p1",
                                       "channel": "outlook"}))

    asyncio.run(bot.on_message_activity(tc))

    assert calls == [{"action": "remind", "pending_id": "p1", "channel": "outlook"}]
    assert tc.sent == []  # the confirm handler owns the reply, not the router
