from botbuilder.schema import Activity
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from eventbuddy.bot.activity_router import EventBuddyBot
from eventbuddy.bot.adapter import build_adapter

router = APIRouter()
_adapter = build_adapter()
_bot = EventBuddyBot()


@router.post("/api/messages")
async def messages(req: Request) -> Response:
    body = await req.json()
    activity = Activity().deserialize(body)
    auth_header = req.headers.get("Authorization", "")
    # For an `invoke` activity (e.g. the Teams OAuth sign-in `signin/verifyState`),
    # `process_activity` returns an `InvokeResponse` and the channel WAITS for it to know the
    # action completed. Returning a bare 200 with no body made the Teams sign-in card render
    # "Something went wrong" even though the bot handled the invoke and acquired the token —
    # so we must write the InvokeResponse (status + body) back. Plain messages return None here.
    invoke_response = await _adapter.process_activity(auth_header, activity, _bot.on_turn)
    if invoke_response is not None:
        return JSONResponse(content=invoke_response.body, status_code=invoke_response.status)
    return Response(status_code=200)
