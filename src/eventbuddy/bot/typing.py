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

from eventbuddy.config import settings

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
    indicator on the Teams side. A no-op when ``TYPING_INDICATOR_ENABLED`` is false — the dev
    kill-switch — so the guarded turn runs untouched and not a single typing activity is sent."""
    if not settings.typing_indicator_enabled:
        yield
        return
    await _send_once(turn_context)
    task = asyncio.create_task(_loop(turn_context))
    try:
        yield
    finally:
        # Cancel *and await* the loop: `cancel()` only requests teardown, so without the await a
        # typing activity already in-flight (or one last re-send) can land on the Teams client
        # AFTER the reply that's sent right after this block — and a typing dot arriving after the
        # last message has nothing to clear it, so the indicator lingers. Awaiting guarantees the
        # loop is fully stopped before the reply goes out, keeping the reply the last activity.
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
