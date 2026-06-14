"""Server-authoritative request context for the conversational agent.

`RequestContext` is built by the server (orchestrator) from the inbound activity — it
carries identity, role, scope and the focused event. It is supplied to the tools via a
factory closure, never as model-settable tool arguments, so the model can neither spoof
*who* the caller is nor *whether* it is allowed (cross-cutting rule 2)."""
from dataclasses import dataclass
from datetime import datetime

from langchain_core.messages import HumanMessage


def event_thread_id(channel_id: str) -> str:
    """The shared-thread memory key for an event channel. Single source of truth so the
    channel scope and the DM→event cross-context read (Phase 1.9) agree on the format."""
    return f"event:{channel_id}"


@dataclass
class RequestContext:
    user_id: str
    channel_id: str | None = None
    # "personal" = 1-1 DM, "channel" = a shared event channel. Drives memory scope.
    scope: str = "personal"
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

    @property
    def thread_id(self) -> str:
        """Scope-aware memory key. A channel shares one thread across its members
        (`event:{channel_id}` — keyed on the channel until channel→event binding lands);
        a 1-1 DM is private (`dm:{user_id}`)."""
        if self.scope == "channel" and self.channel_id:
            return event_thread_id(self.channel_id)
        return f"dm:{self.user_id}"

    def tag(self, text: str) -> HumanMessage:
        """Wrap a human turn, speaker-tagged in shared event threads so the model can
        tell members apart ("remind *me*" resolves to the right person). The send-time
        rides in `additional_kwargs["sent_at"]` (ISO-8601 UTC) — never in `content`, so the
        summarizer's role+content read stays time-agnostic."""
        extra = {}
        if self.sent_at is not None:
            extra["additional_kwargs"] = {"sent_at": self.sent_at.isoformat()}
        if self.scope == "channel" and self.display_name:
            return HumanMessage(content=text, name=self.display_name, **extra)
        return HumanMessage(content=text, **extra)
