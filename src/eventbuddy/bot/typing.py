"""Best-effort Teams typing indicator (Plan 14).

Renders the native "EventBuddy is typing…" dots — the loading-spinner UX — and keeps them
alive across a long synchronous turn by re-sending on an interval. Teams dismisses the
indicator automatically when the bot sends its message reply.

Every send is wrapped: a failed typing activity (transient connector error, a surface that
doesn't support it) must never break the turn — the indicator is best-effort decoration, never
on the critical path (graceful-degradation invariant, CLAUDE.md)."""
import asyncio
from contextlib import asynccontextmanager

from botbuilder.core import TurnContext
from botbuilder.schema import Activity, ActivityTypes

# Teams typing dots fade after a few seconds; re-send comfortably inside that window.
_INTERVAL_S = 2.5


async def _send_once(turn_context: TurnContext) -> None:
    try:
        await turn_context.send_activity(Activity(type=ActivityTypes.typing))
    except Exception:  # noqa: BLE001 — never let the indicator break a turn
        pass


async def _loop(turn_context: TurnContext) -> None:
    try:
        while True:
            await asyncio.sleep(_INTERVAL_S)
            await _send_once(turn_context)
    except asyncio.CancelledError:
        pass


@asynccontextmanager
async def typing_indicator(turn_context: TurnContext):
    """Show the typing indicator for the duration of the `async with` block.

    Sends one dot immediately, then re-sends every ``_INTERVAL_S`` until the block exits (the
    background task is cancelled in the ``finally``). The reply sent after the block clears the
    indicator on the Teams side."""
    await _send_once(turn_context)
    task = asyncio.create_task(_loop(turn_context))
    try:
        yield
    finally:
        task.cancel()
