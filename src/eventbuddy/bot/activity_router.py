import asyncio
import contextvars
import re
from html import unescape
from urllib.parse import urlparse

from botbuilder.core import ActivityHandler, CardFactory, MessageFactory, TurnContext
from botbuilder.schema import InvokeResponse

from eventbuddy.agent.graph import build_agent_graph
from eventbuddy.agent.wiring import build_orchestrator
from eventbuddy.bot.turn_artifacts import begin_artifacts, end_artifacts
from eventbuddy.bot.typing import typing_indicator
from eventbuddy.integrations.graph.delegated import (
    acquire_graph_token,
    clear_signin_needed,
    delegated_enabled,
    send_signin_prompt,
    sign_out_user,
    signin_needed,
)

# Words a user can type to start the Microsoft 365 sign-in flow (Plan 13, delegated auth).
_SIGNIN_COMMANDS = {"sign in", "signin", "sign-in", "log in", "login", "connect", "authenticate"}
# Words a user can type to clear their cached token (force a fresh sign-in/consent — e.g. after
# IT grants a new delegated scope, since the token service caches the old grant).
_SIGNOUT_COMMANDS = {"sign out", "signout", "sign-out", "log out", "logout", "disconnect"}
# A diagnostic command: echo the caller's server-derived identity (the exact `teams_user_id`
# the bot keys everything on) so you can grab it for `make seed HOST_USER_ID=...`. Only ever
# reveals the caller's *own* id to themselves, so it carries no identity-spoofing risk (rule 2).
_WHOAMI_COMMANDS = {"whoami", "who am i", "my id", "myid"}


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
# SharePoint/OneDrive share hosts, for sniffing file links out of the HTML message body
# (Impl 9). Mirrors `capabilities.attachments._SHARE_HOSTS`.
_SHARE_HOSTS = ("sharepoint.com", "onedrive.live.com", "1drv.ms")
# <a href="…">name</a> in the message body — how a file shared *as a link* (not a structured
# attachment) arrives. Captured so a "read this file" turn has a URL, not just a name (Impl 9).
_ANCHOR_RE = re.compile(r'<a\b[^>]*\bhref="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _links_in_html(html: str) -> list[dict]:
    """Pull SharePoint/OneDrive file links out of an HTML message body → `[{name, content_url}]`.
    Teams renders a shared file as an anchor in the body; without this its link is never seen."""
    out: list[dict] = []
    for href, label in _ANCHOR_RE.findall(html or ""):
        host = (urlparse(href).hostname or "").lower()
        if not any(h in host for h in _SHARE_HOSTS):
            continue
        name = unescape(_TAG_RE.sub("", label)).strip() or href.rsplit("/", 1)[-1]
        out.append({"name": name, "content_type": "reference",
                    "download_url": None, "content_url": href})
    return out


def _fetch_my_email(token: str) -> str | None:
    """Resolve the signed-in caller's corporate email via Graph `/me` using their delegated token
    (Impl 18). Synchronous (httpx) — run in an executor from the async handler. Best-effort:
    any failure returns None and the caller falls back to AAD-id matching."""
    from eventbuddy.integrations.graph.client import GraphClient
    from eventbuddy.integrations.graph.delegated import StaticTokenProvider
    try:
        return GraphClient(StaticTokenProvider(token)).get_my_email()
    except Exception:  # noqa: BLE001 — degrade to "email unknown"; aad_object_id still bridges
        return None


def _attachments(activity) -> list[dict]:
    """Lightweight descriptors for incoming file attachments (Impl 4 + Impl 9). A file uploaded
    in Teams arrives as `application/vnd.microsoft.teams.file.download.info` with a
    pre-authenticated `content.downloadUrl`; a file dragged from SharePoint/OneDrive carries a
    `contentUrl`. A file shared *as a link* shows up only as an `<a href>` inside the HTML body
    attachment — we now sniff those out too (Impl 9), so the file's URL is captured, not just its
    name. True Adaptive-Card UI is still ignored. We carry no bytes — a tool downloads on demand
    — so the model can't fabricate a file (rule 2). De-duplicated by URL."""
    out: list[dict] = []
    seen: set[str] = set()

    def add(desc: dict) -> None:
        key = desc.get("download_url") or desc.get("content_url")
        if not key or key in seen:
            return
        seen.add(key)
        out.append(desc)

    for att in getattr(activity, "attachments", None) or []:
        content_type = getattr(att, "content_type", None) or ""
        if content_type == "text/html":
            # The message body — mine it for shared-file anchors, then skip the markup itself.
            body = att.content if isinstance(getattr(att, "content", None), str) else ""
            for desc in _links_in_html(body):
                add(desc)
            continue
        if content_type.startswith(_CARD_PREFIX):
            continue
        content = att.content if isinstance(getattr(att, "content", None), dict) else {}
        download_url = content.get("downloadUrl")
        content_url = getattr(att, "content_url", None)
        if not (download_url or content_url):
            continue
        add({
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
        # Impl 9: resolves a file-picker submit (pending_id + selected names) into a synthesized
        # user turn (text + attachments) that re-enters the agent to answer the original question.
        self._read_files_resolver = getattr(orchestrator, "read_files_resolver", None)
        # Folds a turn's per-recipient teams_dm cards into one before they're sent (or None).
        self._coalesce_cards = getattr(orchestrator, "coalesce_cards", None)
        # Impl 18 — reuse the orchestrator's session store to cache the caller's resolved Graph
        # email (keyed by their stable AAD id), so we don't `/me` on every turn.
        self._session = getattr(orchestrator, "session", None)

    async def _resolve_user_email(self, token: str | None, aad_object_id: str | None) -> str | None:
        """The caller's own corporate email (Impl 18), resolved via Graph `/me` and cached by AAD
        id. Returns None when not signed in (no token) — AAD-id matching still bridges contexts.
        Best-effort and never raises into the turn."""
        if not token:
            return None
        cache_key = aad_object_id or "me"
        store = getattr(self, "_session", None)
        if store is not None:
            cached = store.get_cached_email(cache_key)
            if cached:
                return cached
        try:
            loop = asyncio.get_running_loop()
            email = await loop.run_in_executor(None, _fetch_my_email, token)
        except Exception:  # noqa: BLE001 — degrade: email stays unknown
            email = None
        if email and store is not None:
            store.set_cached_email(cache_key, email)
        return email

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        activity = turn_context.activity

        # An Adaptive Card `Action.Submit` arrives as a message with `activity.value` set.
        # Impl 9 — a file-picker submit is resolved into a synthesized user turn (text +
        # attachments) and re-run through the agent below; everything else (HITL confirms) is
        # routed to the confirm handler (authorized at prepare time; recipients live server-side).
        value = activity.value
        confirm = getattr(self, "_confirm", None)  # defensive: bot may be built via __new__
        synth_text = synth_attachments = None
        if isinstance(value, dict) and value.get("action") == "read_files":
            resolver = getattr(self, "_read_files_resolver", None)
            resolved = resolver(value) if resolver is not None else None
            if not resolved or resolved.get("message"):
                msg = (resolved or {}).get(
                    "message", "That file picker expired — ask me to read the file again.")
                await turn_context.send_activity(msg)
                return
            synth_text = resolved.get("text")
            synth_attachments = resolved.get("attachments") or []
        elif confirm is not None and isinstance(value, dict) and value.get("action"):
            await confirm.handle(turn_context)
            return

        # Bot @mention stripped (group chat / channel) so the LLM sees a clean message; no-op
        # in a 1-1 DM. Used for both the sign-in keyword match and the agent input. A file-picker
        # re-entry overrides this with its synthesized continuation text.
        text = synth_text if synth_text is not None else _clean_text(activity)

        # Plan 13 — an explicit "sign in" message starts the Microsoft 365 sign-in flow (shows
        # the OAuth card). Only meaningful when delegated auth is configured.
        if delegated_enabled() and text.strip().lower() in _SIGNIN_COMMANDS:
            await send_signin_prompt(turn_context)
            return

        # Plan 13 — "sign out" clears the cached token so the next sign-in re-consents with the
        # current scope set (the token service otherwise keeps refreshing the original grant).
        if delegated_enabled() and text.strip().lower() in _SIGNOUT_COMMANDS:
            ok = await sign_out_user(turn_context)
            await turn_context.send_activity(
                "You're signed out of Microsoft 365. Type 'sign in' to reconnect."
                if ok else
                "I couldn't sign you out right now — please try again shortly."
            )
            return

        user_id = activity.from_property.id if activity.from_property else "unknown"
        # Impl 18 — the stable AAD directory object id (server-derived, rule 2). Bridges the Bot
        # Framework `user_id` to Graph chat/channel member listings (which key on this id), so a
        # member enrolled from a group roster is recognized in their own DM.
        aad_object_id = (
            getattr(activity.from_property, "aad_object_id", None)
            if activity.from_property else None
        )

        # Diagnostic: reply with the caller's own server-derived identity so they can copy the
        # exact `teams_user_id` for seeding (`make seed HOST_USER_ID=...`). Placed after
        # `user_id` is resolved; reveals only the caller's own id (no spoofing surface).
        if text.strip().lower() in _WHOAMI_COMMANDS:
            scope_dbg, _ = _scope_and_team(activity)
            name_dbg = activity.from_property.name if activity.from_property else None
            await turn_context.send_activity(
                f"Your Teams user id is:\n\n`{user_id}`\n\n"
                f"AAD object id:\n\n`{aad_object_id or 'unknown'}`\n\n"
                f"(name: {name_dbg or 'unknown'}, scope: {scope_dbg})\n\n"
                f"Use it with: `make seed HOST_USER_ID={user_id}`"
            )
            return

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
        # Impl 18 — resolve the caller's own corporate email (cached) so DM lookups can also match
        # by domain identity, not just the AAD id. None when not signed in (aad still bridges).
        user_email = await self._resolve_user_email(graph_token, aad_object_id)
        # `activity.timestamp` is the channel-set send-time (UTC) — Phase 1.9 keeps it
        # instead of discarding it, so the agent can reason about when messages were sent.
        artifacts, token = begin_artifacts()
        # Plan 14 — show the Teams typing indicator while the turn is prepared. `graph.invoke`
        # is synchronous and blocks the event loop, so we offload it to a thread executor; that
        # lets a background task re-send the typing dots on an interval (an in-loop task would
        # never get scheduled while invoke blocked). `copy_context()` is captured *after*
        # `begin_artifacts()` so the worker thread sees the turn-artifacts ContextVar — cards
        # emitted deep in a tool body must still reach the router after the call returns.
        ctx = contextvars.copy_context()
        loop = asyncio.get_running_loop()
        payload = {
            "user_id": user_id,
            "aad_object_id": aad_object_id,
            "user_email": user_email,
            "channel_id": channel_id,
            "text": text,
            "scope": scope,
            "team_id": team_id,
            "sent_at": activity.timestamp,
            "attachments": (
                synth_attachments if synth_attachments is not None else _attachments(activity)),
            "graph_token": graph_token,
            "display_name": display_name,
        }
        try:
            async with typing_indicator(turn_context):
                result = await loop.run_in_executor(
                    None, lambda: ctx.run(self._graph.invoke, payload)
                )
        finally:
            end_artifacts(token)

        # Track whether the turn put *anything* on the wire. The LLM can end a turn with an empty
        # final message (e.g. it acted via a tool and produced no closing text); if that turn also
        # emits no cards we'd send nothing at all — and with nothing sent, the typing indicator
        # (Plan 14) has no message to clear it and the dots linger. We backstop with a fallback.
        sent_any = False
        reply = result.get("reply")
        if reply:
            await turn_context.send_activity(reply)
            sent_any = True
        # Any cards a tool/capability emitted this turn (e.g. the reminder channel-choice
        # card) are sent as attachments after the text reply. Coalesce first so a flood of
        # per-recipient teams_dm cards collapses to one (no-op when nothing to merge).
        cards = artifacts.cards
        coalesce = getattr(self, "_coalesce_cards", None)  # defensive: bot may be built via __new__
        if coalesce is not None:
            cards = coalesce(cards)
        for card in cards:
            await turn_context.send_activity(
                MessageFactory.attachment(CardFactory.adaptive_card(card))
            )
            sent_any = True
        # Plan 13 — if a Graph-backed tool needed access this turn but the user has no token,
        # auto-prompt sign-in so they can connect and retry (fires only when Graph was actually
        # attempted — never on plain chit-chat).
        if delegated_enabled() and graph_token is None and signin_needed():
            await send_signin_prompt(
                turn_context,
                "To do that I need access to your Microsoft 365 — sign in below, then ask again.",
            )
            sent_any = True
        # Backstop: the turn produced no reply, no cards, and no sign-in prompt. Send a short
        # acknowledgement so the user isn't left staring at a stuck typing indicator (and so the
        # dots clear). Rare — only when the model returns an empty final message with no action.
        if not sent_any:
            await turn_context.send_activity("Sorry, I didn't catch that — could you rephrase?")

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
