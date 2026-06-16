"""Plan 14 — the Teams typing indicator. It must send at least one dot immediately, stop when
the `async with` block exits, and never let a failing send break the turn. No Bot Framework
adapter — a fake TurnContext records (or raises on) sends."""
import asyncio

from botbuilder.schema import ActivityTypes

from eventbuddy.bot import typing as typing_mod
from eventbuddy.bot.typing import typing_indicator


class _TurnContext:
    def __init__(self, fail=False):
        self.sent = []
        self._fail = fail

    async def send_activity(self, a):
        if self._fail:
            raise RuntimeError("connector down")
        self.sent.append(a)


def test_sends_a_typing_dot_immediately():
    tc = _TurnContext()

    async def run():
        async with typing_indicator(tc):
            pass  # fast turn — only the immediate dot fires (loop sleeps first)

    asyncio.run(run())

    assert len(tc.sent) == 1
    assert tc.sent[0].type == ActivityTypes.typing


def test_stops_resending_after_block_exits():
    tc = _TurnContext()

    async def run():
        async with typing_indicator(tc):
            await asyncio.sleep(0)  # yield so the background task starts, then exit
        before = len(tc.sent)
        await asyncio.sleep(0.05)  # well under the re-send interval; nothing more should arrive
        return before

    before = asyncio.run(run())

    assert before == len(tc.sent)  # cancelled cleanly — no more dots after exit


def test_kill_switch_sends_nothing(monkeypatch):
    """With TYPING_INDICATOR_ENABLED off, the dev kill-switch, the block runs but no typing
    activity is ever sent."""
    monkeypatch.setattr(typing_mod.settings, "typing_indicator_enabled", False)
    tc = _TurnContext()
    ran = []

    async def run():
        async with typing_indicator(tc):
            ran.append(True)
            await asyncio.sleep(0.05)  # past the re-send interval would-be window

    asyncio.run(run())

    assert ran == [True]  # guarded work still runs
    assert tc.sent == []  # but not one dot was sent


def test_send_failure_never_breaks_the_block():
    tc = _TurnContext(fail=True)
    ran = []

    async def run():
        async with typing_indicator(tc):
            ran.append(True)  # the guarded work still runs despite typing sends failing

    asyncio.run(run())

    assert ran == [True]
    assert tc.sent == []
