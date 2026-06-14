from fastapi import APIRouter, Request, Response

from eventbuddy.common.logging import get_logger

router = APIRouter()
log = get_logger("api.webhooks")


@router.post("/api/webhooks/graph")
async def graph_webhook(req: Request) -> Response:
    token = req.query_params.get("validationToken")
    if token:
        # Subscription validation handshake — echo the token as text/plain.
        return Response(content=token, media_type="text/plain", status_code=200)
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001 — empty/invalid body: ack and move on
        body = {}
    try:
        from eventbuddy.data.redis import get_redis
        from eventbuddy.ingestion.webhook import handle_notifications
        handle_notifications(body, redis_client=get_redis())
    except Exception as e:  # noqa: BLE001 — never 5xx a webhook (Graph would retry forever)
        log.warning(f"graph webhook handling failed ({type(e).__name__}: {e})")
    return Response(status_code=202)
