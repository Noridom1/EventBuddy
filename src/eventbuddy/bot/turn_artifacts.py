"""Request-scoped side-channel for things a turn produces *besides* its text reply —
today just Adaptive Cards (Implementation 1, HITL action plane).

The agent path is string-in/string-out: `Orchestrator.handle(...) -> str`. A tool body
(e.g. `prepare_reminders` → `remind_fn`) runs several frames below `handle`, inside the
synchronous `graph.invoke`, with no access to the `TurnContext` — so it cannot send a card
directly. This mirrors the Phase 1.8 `ToolTrace` mechanism exactly: a `ContextVar` set by
the activity router immediately before `graph.invoke` and reset in a `finally`. Because the
whole chain is synchronous-inline under `.invoke`, a card `emit_card(...)`-ed deep in a tool
body is visible to the router after the call returns. Keeps `handle()`'s `str` contract
(the load-bearing stable-signature rule) intact.

`emit_card` is a no-op when no artifacts context is active (unit tests calling capability
closures directly), so nothing breaks off the request path."""
from contextvars import ContextVar
from dataclasses import dataclass, field

# Set by the router (and the dev route) around the agent invocation; reset in a finally.
_current: ContextVar["TurnArtifacts | None"] = ContextVar(
    "eventbuddy_turn_artifacts", default=None
)


@dataclass
class TurnArtifacts:
    """Collected over one `handle(...)` call. `cards` are Adaptive Card payloads the router
    sends as attachments after the text reply."""

    cards: list[dict] = field(default_factory=list)


def begin_artifacts() -> tuple[TurnArtifacts, object]:
    """Start a fresh artifacts collector for one request; returns it plus the reset token."""
    artifacts = TurnArtifacts()
    token = _current.set(artifacts)
    return artifacts, token


def end_artifacts(token: object) -> None:
    _current.reset(token)


def emit_card(card: dict) -> None:
    """Queue an Adaptive Card for the active turn. No-op when no artifacts context is set."""
    artifacts = _current.get()
    if artifacts is not None:
        artifacts.cards.append(card)
