"""Dev-only debug route. Lets you POST a message and see the orchestrator's routed
reply directly over HTTP — bypassing the Bot Framework async ack path. Mounted only
when `settings.dev_routes_enabled` is true (env DEV_ROUTES_ENABLED=true). Never enable
in production: it has no Bot Framework JWT auth."""
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from eventbuddy.agent.graph import build_agent_graph
from eventbuddy.agent.wiring import build_orchestrator

router = APIRouter()

_graph = None


def get_graph():
    """Lazily build the production orchestrator graph once; overridable in tests."""
    global _graph
    if _graph is None:
        _graph = build_agent_graph(build_orchestrator())
    return _graph


class HandleRequest(BaseModel):
    text: str
    user_id: str = "dev-user"
    channel_id: str | None = None


@router.post("/api/dev/handle")
async def dev_handle(body: HandleRequest, graph: Annotated[object, Depends(get_graph)]) -> dict:
    try:
        out = graph.invoke(
            {"user_id": body.user_id, "channel_id": body.channel_id, "text": body.text}
        )
        return {"reply": out["reply"]}
    except Exception as e:
        # Data-backed intents need Postgres/Redis/Graph creds; surface the cause plainly
        # instead of a 500 so the route stays useful for probing what's wired up.
        return {"error": f"{type(e).__name__}: {e}"}
