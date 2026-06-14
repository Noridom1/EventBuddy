"""Dev-only debug route. Lets you POST a message and see the orchestrator's routed
reply directly over HTTP — bypassing the Bot Framework async ack path. Mounted only
when `settings.dev_routes_enabled` is true (env DEV_ROUTES_ENABLED=true). Never enable
in production: it has no Bot Framework JWT auth.

The route is **DM-scoped**: it keys conversation memory on `dm:{user_id}`, so repeated
POSTs with the same `user_id` continue one multi-turn conversation. Pass `reset: true` to
start a fresh thread."""
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from eventbuddy.agent.wiring import build_orchestrator
from eventbuddy.bot.turn_artifacts import begin_artifacts, end_artifacts

router = APIRouter()

_orchestrator = None


def get_orchestrator():
    """Lazily build the production orchestrator once; overridable in tests."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = build_orchestrator()
    return _orchestrator


class HandleRequest(BaseModel):
    text: str
    user_id: str = "dev-user"
    reset: bool = False
    # Impl 3: exercise channel scope (brainstorm) over HTTP without the Emulator. Defaults
    # keep the route DM-scoped as before.
    scope: str = "personal"
    channel_id: str | None = None
    team_id: str | None = None


class ConfirmRequest(BaseModel):
    """Simulates an Adaptive Card `Action.Submit` click without the Emulator (which, against
    a remote/deployed bot, would need ngrok for the async reply). `pending_id` comes from the
    card emitted by a prior `/api/dev/handle` turn; `user_id` must match that turn's user
    (the confirm re-auth requires clicker == preparer)."""

    pending_id: str
    action: str = "remind"
    channel: str | None = "outlook"
    user_id: str = "dev-user"


@router.post("/api/dev/handle")
async def dev_handle(
    body: HandleRequest, orch: Annotated[object, Depends(get_orchestrator)]
) -> dict:
    try:
        if body.reset:
            orch.reset_dm(body.user_id)
        # Collect any Adaptive Cards the turn emits (HITL flows) so they're testable over HTTP.
        artifacts, token = begin_artifacts()
        try:
            reply = orch.handle(
                user_id=body.user_id, channel_id=body.channel_id, text=body.text,
                scope=body.scope, team_id=body.team_id,
                sent_at=datetime.now(UTC),  # dev turns stamped "now" so L2 carries a send-time
            )
        finally:
            end_artifacts(token)
        result = {"reply": reply}
        if artifacts.cards:  # only when a HITL flow emitted one — keeps the plain shape stable
            result["cards"] = artifacts.cards
        return result
    except Exception as e:
        # Data-backed intents need Postgres/Redis/Graph creds; surface the cause plainly
        # instead of a 500 so the route stays useful for probing what's wired up.
        return {"error": f"{type(e).__name__}: {e}"}


@router.post("/api/dev/confirm")
async def dev_confirm(
    body: ConfirmRequest, orch: Annotated[object, Depends(get_orchestrator)]
) -> dict:
    confirm = getattr(orch, "confirm_handler", None)
    if confirm is None:
        return {"error": "confirm handler not wired (LLM/Graph path unavailable)"}
    try:
        reply = confirm.resolve(
            action=body.action, pending_id=body.pending_id,
            channel=body.channel, clicker=body.user_id,
        )
        return {"reply": reply}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
