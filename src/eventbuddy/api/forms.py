"""Feedback intake endpoint — the **fallback** push path (e.g. a Power Automate flow on
"When a new response is submitted"). The chosen feedback-fetch path is the Excel-workbook
sync (`capabilities/forms_sync.py`); this endpoint is kept thin and is not the demo's tested
intake. It stores a raw response + the LLM sentiment/theme analysis, then acks 202."""
from fastapi import APIRouter, Request, Response

from eventbuddy.common.logging import get_logger

router = APIRouter()
log = get_logger("api.forms")


def ingest_response(payload: dict, *, repo, analyzer) -> None:
    """Core (session-bound `repo` injected) — analyze the comment + store one response."""
    comment = payload.get("comment", "")
    sentiment, themes = analyzer.analyze(comment)
    repo.add(
        payload["event_id"],
        respondent_id=payload.get("respondent_id") or payload.get("email"),
        raw_payload={"rating": payload.get("rating"), "comment": comment,
                     "email": payload.get("email")},
        sentiment=sentiment,
        themes={"tags": themes},
    )


def _ingest(payload: dict) -> None:
    from eventbuddy.data.db import session_scope
    from eventbuddy.data.repositories.feedback import FeedbackRepository
    from eventbuddy.domain.feedback import FeedbackAnalyzer
    from eventbuddy.integrations.llm.client import LLMGateway

    with session_scope() as s:
        ingest_response(
            payload, repo=FeedbackRepository(s), analyzer=FeedbackAnalyzer(LLMGateway()))


@router.post("/api/webhooks/forms")
async def forms_ingest(req: Request) -> Response:
    payload = await req.json()
    try:
        _ingest(payload)
    except Exception as e:  # noqa: BLE001 — never 5xx a webhook (the sender would retry)
        log.warning(f"forms ingest failed ({type(e).__name__}: {e})")
    return Response(status_code=202)
