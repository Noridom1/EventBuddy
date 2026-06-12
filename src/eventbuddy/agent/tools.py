"""LangChain tool registry over the event capabilities.

Each tool's **docstring is the model-facing description** — keep them action-oriented.
Identity/role/focused-event come from the server-built `RequestContext` captured in the
factory closure, so they are NOT in any tool's argument schema and cannot be model-set
(cross-cutting rule 2). The tool bodies delegate to the same `*_fn` capability closures
used by the Phase 1 orchestrator (DRY) — see `wiring.py`."""
from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.tools import BaseTool, tool

from eventbuddy.agent.context import RequestContext
from eventbuddy.bot.auth import ROLE_RANK


@dataclass
class AgentDeps:
    """The capability callables + app-state store the tools delegate to."""

    session_store: object
    provision_fn: Callable
    resolve_event_fn: Callable
    remind_fn: Callable
    report_fn: Callable
    query_tasks_fn: Callable


def _role_allows(ctx: RequestContext, min_role: str) -> bool:
    return ROLE_RANK.get(ctx.role, 0) >= ROLE_RANK[min_role]


def build_tools(deps: AgentDeps, ctx: RequestContext) -> list[BaseTool]:
    """Build the per-request tool set bound to this caller's context."""

    @tool
    def create_event(
        name: str, member_emails: list[str], objective: str = ""
    ) -> str:
        """Create a new event with the given name and member email addresses.
        Use only when the user explicitly asks to create/set up/start an event.
        `member_emails` is the roster of participant email addresses."""
        if not _role_allows(ctx, "moderator"):
            return "You don't have permission to create events (needs host or moderator)."
        ev = deps.provision_fn(
            name=name, host_user_id=ctx.user_id, member_emails=member_emails, objective=objective
        )
        return f"Created event '{name}' (id {ev.event_id})."

    @tool
    def set_focus_event(event_query: str) -> str:
        """Switch the focused event to the one matching `event_query` (a name or fragment).
        Subsequent task/reminder/report actions apply to this event."""
        event_id = deps.resolve_event_fn(event_query)
        if not event_id:
            return f"I couldn't find an event matching '{event_query}'."
        deps.session_store.set_current_event(ctx.user_id, event_id)
        return f"Focused on '{event_query}'."

    @tool
    def prepare_reminders(note: str = "") -> str:
        """Prepare reminders for the members of the currently focused event.
        Optionally pass a `note` to include. Requires a focused event."""
        if not _role_allows(ctx, "moderator"):
            return "You don't have permission to send reminders (needs host or moderator)."
        event_id = deps.session_store.get_current_event(ctx.user_id)
        if not event_id:
            return "No event is focused yet — tell me which event first."
        deps.remind_fn(event_id=event_id, user_id=ctx.user_id, raw=note)
        return "I prepared the reminders — pick a channel on the card above."

    @tool
    def list_my_tasks() -> str:
        """List the caller's assigned tasks in the currently focused event."""
        event_id = deps.session_store.get_current_event(ctx.user_id)
        return deps.query_tasks_fn(user_id=ctx.user_id, event_id=event_id)

    @tool
    def generate_report() -> str:
        """Generate the AI summary report for the currently focused event."""
        event_id = deps.session_store.get_current_event(ctx.user_id)
        return deps.report_fn(event_id=event_id)

    return [create_event, set_focus_event, prepare_reminders, list_my_tasks, generate_report]
