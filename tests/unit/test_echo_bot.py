import pytest
from botbuilder.core.adapters import TestAdapter

from eventbuddy.bot.activity_router import EventBuddyBot


@pytest.mark.asyncio
async def test_bot_replies_with_routed_reply(monkeypatch):
    # Avoid real Redis/DB: stub the orchestrator graph.
    bot = EventBuddyBot.__new__(EventBuddyBot)
    bot._graph = type("G", (), {"invoke": lambda self, s: {"reply": "Hi!"}})()
    adapter = TestAdapter(bot.on_turn)
    await adapter.test("hello", "Hi!")
