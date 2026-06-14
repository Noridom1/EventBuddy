from botbuilder.core import ActivityHandler, CardFactory, MessageFactory, TurnContext

from eventbuddy.agent.graph import build_agent_graph
from eventbuddy.agent.wiring import build_orchestrator
from eventbuddy.bot.turn_artifacts import begin_artifacts, end_artifacts


def _scope_and_team(activity) -> tuple[str, str | None]:
    """Derive conversation scope + the real Teams team id from a Bot Framework activity
    (Impl 3). A channel message has `conversation.conversation_type == "channel"` and carries
    the team id in `channel_data.team.id`; everything else is treated as a 1-1 "personal"
    chat. Group chats are not channels (no team/SharePoint backing), so they stay personal."""
    conv = activity.conversation
    conv_type = getattr(conv, "conversation_type", None) if conv else None
    if conv_type != "channel":
        return "personal", None
    team_id = None
    data = activity.channel_data
    if isinstance(data, dict):
        team = data.get("team")
        if isinstance(team, dict):
            team_id = team.get("id")
    return "channel", team_id


_CARD_PREFIX = "application/vnd.microsoft.card"


def _attachments(activity) -> list[dict]:
    """Lightweight descriptors for incoming file attachments (Impl 4). A file uploaded in
    Teams arrives as `application/vnd.microsoft.teams.file.download.info` with a
    pre-authenticated `content.downloadUrl`; a file dragged from SharePoint/OneDrive carries a
    `contentUrl`. Adaptive-card and HTML (the message body) attachments are skipped. We carry
    no bytes — a tool downloads on demand — so the model can't fabricate a file (rule 2)."""
    out: list[dict] = []
    for att in getattr(activity, "attachments", None) or []:
        content_type = getattr(att, "content_type", None) or ""
        if content_type.startswith(_CARD_PREFIX) or content_type == "text/html":
            continue
        content = att.content if isinstance(getattr(att, "content", None), dict) else {}
        download_url = content.get("downloadUrl")
        content_url = getattr(att, "content_url", None)
        if not (download_url or content_url):
            continue
        out.append({
            "name": getattr(att, "name", None) or content.get("fileName") or "",
            "content_type": content_type,
            "download_url": download_url,
            "content_url": content_url,
        })
    return out


class EventBuddyBot(ActivityHandler):
    def __init__(self):
        orchestrator = build_orchestrator()
        self._graph = build_agent_graph(orchestrator)
        # HITL confirm loop (Impl 1): handles Adaptive Card `Action.Submit` clicks.
        self._confirm = getattr(orchestrator, "confirm_handler", None)

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        activity = turn_context.activity

        # An Adaptive Card `Action.Submit` arrives as a message with `activity.value` set —
        # route it to the confirm handler instead of the agent (it was authorized at prepare
        # time; recipients live server-side, not in the model's head).
        value = activity.value
        confirm = getattr(self, "_confirm", None)  # defensive: bot may be built via __new__
        if confirm is not None and isinstance(value, dict) and value.get("action"):
            await confirm.handle(turn_context)
            return

        user_id = activity.from_property.id if activity.from_property else "unknown"
        channel_id = activity.conversation.id if activity.conversation else None
        # Scope + team id (Impl 3). Without this, every message — even one in a channel — was
        # treated as a DM, and channel Graph calls used the tenant id instead of the team id.
        scope, team_id = _scope_and_team(activity)
        # `activity.timestamp` is the channel-set send-time (UTC) — Phase 1.9 keeps it
        # instead of discarding it, so the agent can reason about when messages were sent.
        artifacts, token = begin_artifacts()
        try:
            result = self._graph.invoke(
                {
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "text": activity.text or "",
                    "scope": scope,
                    "team_id": team_id,
                    "sent_at": activity.timestamp,
                    "attachments": _attachments(activity),
                }
            )
        finally:
            end_artifacts(token)

        reply = result.get("reply")
        if reply:
            await turn_context.send_activity(reply)
        # Any cards a tool/capability emitted this turn (e.g. the reminder channel-choice
        # card) are sent as attachments after the text reply.
        for card in artifacts.cards:
            await turn_context.send_activity(
                MessageFactory.attachment(CardFactory.adaptive_card(card))
            )
