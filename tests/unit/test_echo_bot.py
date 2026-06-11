import pytest
from botbuilder.core.adapters import TestAdapter

from eventbuddy.bot.activity_router import EventBuddyBot


@pytest.mark.asyncio
async def test_echo_bot_echoes_message():
    bot = EventBuddyBot()
    adapter = TestAdapter(bot.on_turn)
    await adapter.test("hello", "Echo: hello")
