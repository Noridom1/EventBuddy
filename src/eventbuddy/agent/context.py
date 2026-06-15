"""Server-authoritative request context for the conversational agent.

`RequestContext` is built by the server (orchestrator) from the inbound activity — it
carries identity, role, scope and the focused event. It is supplied to the tools via a
factory closure, never as model-settable tool arguments, so the model can neither spoof
*who* the caller is nor *whether* it is allowed (cross-cutting rule 2)."""
from dataclasses import dataclass, field
from datetime import datetime

from langchain_core.messages import HumanMessage


def event_thread_id(channel_id: str) -> str:
    """The shared-thread memory key for an event channel. Single source of truth so the
    channel scope and the DM→event cross-context read (Phase 1.9) agree on the format."""
    return f"event:{channel_id}"


def focus_key_for(scope: str, user_id: str, channel_id: str | None) -> str:
    """The session-store key under which the *focused event* is stored. In a group chat the
    focus is shared across the members (keyed on the chat's conversation id) so everyone sees
    the same event; in a 1-1 DM it's the caller's own. Channel scope never uses the session
    store for focus (it resolves the channel→event binding), so its value here is irrelevant.
    Single source of truth shared by `Orchestrator._build_ctx` and `RequestContext.focus_key`."""
    if scope == "group" and channel_id:
        return f"group:{channel_id}"
    return user_id


@dataclass
class RequestContext:
    user_id: str
    channel_id: str | None = None
    # "personal" = 1-1 DM, "channel" = a shared event channel. Drives memory scope.
    scope: str = "personal"
    # Real Teams team/group id this conversation lives under (channel scope only — None in a
    # group chat or DM). Server-derived from `activity.channel_data.team.id` (rule 2). Carried
    # so `setup_event` can persist it onto the bound event for later channel Graph calls.
    team_id: str | None = None
    # The caller's role for permission checks (server-resolved). Read-only tools ignore it.
    role: str = "member"
    # The session's focused event; resolved server-side, not model-supplied.
    current_event_id: str | None = None
    # Display name for speaker-tagging in shared event threads.
    display_name: str | None = None
    # Real send-time of this turn (Bot Framework `activity.timestamp`, channel-set UTC),
    # captured at ingress (Phase 1.9). Rides in the human turn's `additional_kwargs`; the
    # transcript persists it (the L2 `sent_at` column) so the agent can reason about recency.
    sent_at: datetime | None = None
    # Lightweight descriptors of files the user attached this turn (Impl 4) —
    # `{name, content_type, download_url, content_url}`, never bytes. Server-built from the
    # inbound activity, so the model can't fabricate a file (rule 2). A tool
    # (`read_participant_file`) downloads + parses on demand.
    attachments: list[dict] = field(default_factory=list)
    # Delegated Microsoft Graph bearer token for this caller (Plan 13). Acquired server-side
    # from the Bot Framework token service (Teams SSO / OAuth connection) at ingress — never
    # model-supplied (rule 2). None when delegated auth isn't configured, or the user hasn't
    # signed in yet; the runner publishes it to a request-scoped ContextVar that
    # `wiring.graph_for()` reads, so Graph calls act on behalf of this user.
    graph_token: str | None = None

    @property
    def thread_id(self) -> str:
        """Scope-aware memory key. A channel shares one thread across its members
        (`event:{channel_id}` — keyed on the channel until channel→event binding lands); a
        group chat likewise shares one thread (`group:{channel_id}`, keyed on the chat's
        conversation id) so the bot sees the whole multi-person conversation as one; a 1-1 DM
        is private (`dm:{user_id}`)."""
        if self.scope == "channel" and self.channel_id:
            return event_thread_id(self.channel_id)
        if self.scope == "group" and self.channel_id:
            return f"group:{self.channel_id}"
        return f"dm:{self.user_id}"

    @property
    def focus_key(self) -> str:
        """Session-store key for this turn's focused event — shared in a group chat, per-user
        in a DM. See `focus_key_for`."""
        return focus_key_for(self.scope, self.user_id, self.channel_id)

    def tag(self, text: str) -> HumanMessage:
        """Wrap a human turn, speaker-tagged in shared event threads so the model can
        tell members apart ("remind *me*" resolves to the right person). The send-time
        rides in `additional_kwargs["sent_at"]` (ISO-8601 UTC) — never in `content`, so the
        summarizer's role+content read stays time-agnostic."""
        extra = {}
        if self.sent_at is not None:
            extra["additional_kwargs"] = {"sent_at": self.sent_at.isoformat()}
        if self.scope in ("channel", "group") and self.display_name:
            return HumanMessage(content=text, name=self.display_name, **extra)
        return HumanMessage(content=text, **extra)
