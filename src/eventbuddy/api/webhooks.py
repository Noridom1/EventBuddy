from fastapi import APIRouter, Request, Response

router = APIRouter()


@router.post("/api/webhooks/graph")
async def graph_webhook(req: Request) -> Response:
    token = req.query_params.get("validationToken")
    if token:
        return Response(content=token, media_type="text/plain", status_code=200)
    # Phase 2 enqueues ingestion here; Phase 0 just acks.
    return Response(status_code=202)
