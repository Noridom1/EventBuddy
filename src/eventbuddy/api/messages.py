from botbuilder.schema import Activity
from fastapi import APIRouter, Request, Response

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
    await _adapter.process_activity(auth_header, activity, _bot.on_turn)
    return Response(status_code=200)
