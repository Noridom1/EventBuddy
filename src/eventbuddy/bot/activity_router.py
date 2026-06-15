from botbuilder.core import ActivityHandler, CardFactory, MessageFactory, TurnContext
from botbuilder.schema import InvokeResponse

from eventbuddy.agent.graph import build_agent_graph
from eventbuddy.agent.wiring import build_orchestrator
from eventbuddy.bot.turn_artifacts import begin_artifacts, end_artifacts
from eventbuddy.integrations.graph.delegated import (
    acquire_graph_token,
    clear_signin_needed,
    delegated_enabled,
    send_signin_prompt,
    signin_needed,
)

# Words a user can type to start the Microsoft 365 sign-in flow (Plan 13, delegated auth).
_SIGNIN_COMMANDS = {"sign in", "signin", "sign-in", "log in", "login", "connect", "authenticate"}


def _scope_and_team(activity) -> tuple[str, str | None]:
    """Derive conversation scope + the real Teams team id from a Bot Framework activity
    (Impl 3). A channel message has `conversation.conversation_type == "channel"` and carries
    the team id in `channel_data.team.id`. A multi-person group chat is `"groupChat"` — not a
    channel (no team/SharePoint backing), but still a *shared* conversation, so it gets its own
    "group" scope (one memory thread per chat, members speaker-tagged). Everything else (a 1-1
    DM) is "personal"."""
    conv = activity.conversation
    conv_type = getattr(conv, "conversation_type", None) if conv else None
    if conv_type == "groupChat":
        return "group", None
    if conv_type != "channel":
        return "personal", None
    team_id = None
    data = activity.channel_data
    if isinstance(data, dict):
        team = data.get("team")
        if isinstance(team, dict):
            team_id = team.get("id")
    return "channel", team_id


def _clean_text(activity) -> str:
    """The user's message with the bot's own @mention stripped. In a group chat or channel the
    bot only receives messages that @mention it, and `activity.text` includes the literal
    "EventBuddy " mention — noise that would otherwise reach the LLM. In a 1-1 DM there is no
    mention, so this is a no-op. Defensive: any parsing hiccup falls back to the raw text."""
    text = activity.text or ""
    try:
        if getattr(activity, "entities", None):
            return (TurnContext.remove_recipient_mention(activity) or text).strip()
    except Exception:  # noqa: BLE001 — never let mention-stripping break a turn
        pass
    return text


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

        # Bot @mention stripped (group chat / channel) so the LLM sees a clean message; no-op
        # in a 1-1 DM. Used for both the sign-in keyword match and the agent input.
        text = _clean_text(activity)

        # Plan 13 — an explicit "sign in" message starts the Microsoft 365 sign-in flow (shows
        # the OAuth card). Only meaningful when delegated auth is configured.
        if delegated_enabled() and text.strip().lower() in _SIGNIN_COMMANDS:
            await send_signin_prompt(turn_context)
            return

        user_id = activity.from_property.id if activity.from_property else "unknown"
        # Speaker name for tagging members apart in shared (group/channel) threads (rule 2:
        # server-derived, never model-supplied). None in a DM, where tagging is off anyway.
        display_name = activity.from_property.name if activity.from_property else None
        channel_id = activity.conversation.id if activity.conversation else None
        # Scope + team id (Impl 3). Without this, every message — even one in a channel — was
        # treated as a DM, and channel Graph calls used the tenant id instead of the team id.
        scope, team_id = _scope_and_team(activity)
        # Plan 13 — delegated Graph auth: acquire the caller's Graph token from the Bot
        # Framework token service here, where the TurnContext exists. None when delegated auth
        # isn't configured or the user isn't signed in yet — Graph-backed tools then degrade
        # cleanly. Identity-bound + server-acquired, never model-supplied (rule 2).
        graph_token = await acquire_graph_token(turn_context)
        clear_signin_needed()  # reset the per-turn "Graph needed but no token" flag
        # `activity.timestamp` is the channel-set send-time (UTC) — Phase 1.9 keeps it
        # instead of discarding it, so the agent can reason about when messages were sent.
        artifacts, token = begin_artifacts()
        try:
            result = self._graph.invoke(
                {
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "text": text,
                    "scope": scope,
                    "team_id": team_id,
                    "sent_at": activity.timestamp,
                    "attachments": _attachments(activity),
                    "graph_token": graph_token,
                    "display_name": display_name,
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
        # Plan 13 — if a Graph-backed tool needed access this turn but the user has no token,
        # auto-prompt sign-in so they can connect and retry (fires only when Graph was actually
        # attempted — never on plain chit-chat).
        if delegated_enabled() and graph_token is None and signin_needed():
            await send_signin_prompt(
                turn_context,
                "To do that I need access to your Microsoft 365 — sign in below, then ask again.",
            )

    async def on_invoke_activity(self, turn_context: TurnContext) -> InvokeResponse:
        """Complete the Teams sign-in flow. After the user finishes the OAuth card, Teams sends
        a `signin/verifyState` (magic code) or `signin/tokenExchange` (SSO) invoke; we fetch the
        now-issued token and confirm. Anything else falls through to the base handler."""
        name = turn_context.activity.name
        if name in ("signin/verifyState", "signin/tokenExchange"):
            value = turn_context.activity.value if isinstance(turn_context.activity.value, dict) \
                else {}
            token = await acquire_graph_token(turn_context, magic_code=value.get("state"))
            if token:
                await turn_context.send_activity(
                    "✅ You're signed in. Ask me again and I'll act on your behalf in Microsoft "
                    "365."
                )
            else:
                await turn_context.send_activity(
                    "I couldn't complete the sign-in — please try 'sign in' again."
                )
            return InvokeResponse(status=200)
        return await super().on_invoke_activity(turn_context)
