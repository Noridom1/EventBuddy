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


@router.post("/api/dev/handle")
async def dev_handle(
    body: HandleRequest, orch: Annotated[object, Depends(get_orchestrator)]
) -> dict:
    try:
        if body.reset:
            orch.reset_dm(body.user_id)
        reply = orch.handle(
            user_id=body.user_id, channel_id=None, text=body.text, scope="personal",
            sent_at=datetime.now(UTC),  # dev turns are stamped "now" so L2 carries a send-time
        )
        return {"reply": reply}
    except Exception as e:
        # Data-backed intents need Postgres/Redis/Graph creds; surface the cause plainly
        # instead of a 500 so the route stays useful for probing what's wired up.
        return {"error": f"{type(e).__name__}: {e}"}
