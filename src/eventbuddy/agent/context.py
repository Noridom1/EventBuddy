"""Server-authoritative request context for the conversational agent.

`RequestContext` is built by the server (orchestrator) from the inbound activity — it
carries identity, role, scope and the focused event. It is supplied to the tools via a
factory closure, never as model-settable tool arguments, so the model can neither spoof
*who* the caller is nor *whether* it is allowed (cross-cutting rule 2)."""
from dataclasses import dataclass

from langchain_core.messages import HumanMessage


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

    @property
    def thread_id(self) -> str:
        """Scope-aware memory key. A channel shares one thread across its members
        (`event:{channel_id}` — keyed on the channel until channel→event binding lands);
        a 1-1 DM is private (`dm:{user_id}`)."""
        if self.scope == "channel" and self.channel_id:
            return f"event:{self.channel_id}"
        return f"dm:{self.user_id}"

    def tag(self, text: str) -> HumanMessage:
        """Wrap a human turn, speaker-tagged in shared event threads so the model can
        tell members apart ("remind *me*" resolves to the right person)."""
        if self.scope == "channel" and self.display_name:
            return HumanMessage(content=text, name=self.display_name)
        return HumanMessage(content=text)
