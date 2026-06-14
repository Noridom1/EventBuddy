"""LangChain tool registry over the event capabilities.

Each tool's **docstring is the model-facing description** — keep them action-oriented.
Identity/role/focused-event come from the server-built `RequestContext` captured in the
factory closure, so they are NOT in any tool's argument schema and cannot be model-set
(cross-cutting rule 2). The tool bodies delegate to the same `*_fn` capability closures
used by the Phase 1 orchestrator (DRY) — see `wiring.py`.

**Phase 1.8 — tool tracing.** Every tool call this turn is recorded into a request-scoped
`ToolTrace` (a `ContextVar` set by the runner around `agent.invoke`) with the params the
model passed and, on failure, the exception + traceback. The runner reads the trace to
build the debug footer. In debug mode a failing tool returns a soft error string so the
loop continues and the model can acknowledge it; with debug off the wrapper re-raises so
the orchestrator's graceful regex fallback still fires (unchanged behavior)."""
import functools
import traceback
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field

from langchain_core.tools import BaseTool, tool

from eventbuddy.agent.context import RequestContext
from eventbuddy.bot.auth import ROLE_RANK


@dataclass
class ToolCallRecord:
    """One tool invocation this turn. `params` is exactly what the model passed —
    never identity/role/scope (those come from the closed-over `RequestContext`)."""

    tool: str
    params: dict
    ok: bool
    error: str | None = None
    traceback: str | None = None


@dataclass
class ToolTrace:
    records: list[ToolCallRecord] = field(default_factory=list)

    def add(self, rec: ToolCallRecord) -> None:
        self.records.append(rec)

    @property
    def errored(self) -> list[ToolCallRecord]:
        return [r for r in self.records if not r.ok]


# Set by the runner immediately before `agent.invoke` and reset in a `finally`. The tool
# loop runs synchronously on the request thread under `.invoke`, so the value is visible to
# the wrapped tool bodies and isolated per request (one ContextVar copy per worker thread).
_current_trace: ContextVar[ToolTrace | None] = ContextVar("eventbuddy_tool_trace", default=None)


def begin_trace() -> tuple[ToolTrace, object]:
    """Start a fresh trace for one request; returns it plus the reset token."""
    trace = ToolTrace()
    token = _current_trace.set(trace)
    return trace, token


def end_trace(token: object) -> None:
    _current_trace.reset(token)


def _make_traced(debug: bool) -> Callable:
    """Build the per-request tool-body wrapper. Records every call into the active
    `ToolTrace`; on exception records the error + traceback, then returns a soft error
    string when `debug` (loop continues) or re-raises otherwise (regex fallback fires)."""

    def _traced(fn: Callable) -> Callable:
        @functools.wraps(fn)  # preserve name/doc/signature so @tool builds the right schema
        def wrapper(*args, **kwargs):
            trace = _current_trace.get()
            params = dict(kwargs)
            try:
                result = fn(*args, **kwargs)
                if trace is not None:
                    trace.add(ToolCallRecord(fn.__name__, params, ok=True))
                return result
            except Exception as e:  # noqa: BLE001 — captured for the debug footer
                if trace is not None:
                    trace.add(ToolCallRecord(
                        fn.__name__, params, ok=False,
                        error=f"{type(e).__name__}: {e}", traceback=traceback.format_exc(),
                    ))
                if debug:
                    return f"⚠️ {fn.__name__} failed: {type(e).__name__}: {e}"
                raise

        return wrapper

    return _traced


def _no_event_context(**_kw) -> str:
    """Default `event_context_fn` — cross-context read disabled (no LLM path wired)."""
    return ""


def _no_update_task(**_kw) -> str:
    """Default `update_task_fn` — task updates not wired (no DB path)."""
    return "Task updates aren't available right now."


def _no_send_mail(**_kw) -> str:
    """Default `send_mail_fn` — outbound mail not wired (no Graph/HITL path)."""
    return "Sending mail isn't available right now."


def _no_ingest(**_kw) -> str:
    """Default `ingest_fn` — document/SharePoint ingestion not wired (no Graph path)."""
    return "File access isn't available right now."


@dataclass
class AgentDeps:
    """The capability callables + app-state store the tools delegate to."""

    session_store: object
    provision_fn: Callable
    resolve_event_fn: Callable
    remind_fn: Callable
    report_fn: Callable
    query_tasks_fn: Callable
    # Phase 1.9 — the single guarded DM→event cross-context read (`load_event_context`).
    # Defaults to a no-op so callers/tests that don't wire it (no LLM path) still build.
    event_context_fn: Callable = _no_event_context
    # Impl 1 (action plane) — `update_task` (direct) + `send_outlook_mail` (HITL). Default to
    # no-ops so the existing tests/no-DB path still build the tool set.
    update_task_fn: Callable = _no_update_task
    send_mail_fn: Callable = _no_send_mail
    # Impl 2 (intelligence plane) — `ingest_event_files` pulls the channel's SharePoint files
    # (or a pasted link) through the parse→structure→upsert pipeline. Default no-op.
    ingest_fn: Callable = _no_ingest
    # When True, tool failures are softened (recorded + returned as a string) so the runner
    # can surface them in the debug footer; when False, they re-raise (regex fallback).
    debug: bool = False


def _role_allows(ctx: RequestContext, min_role: str) -> bool:
    return ROLE_RANK.get(ctx.role, 0) >= ROLE_RANK[min_role]


def build_tools(deps: AgentDeps, ctx: RequestContext) -> list[BaseTool]:
    """Build the per-request tool set bound to this caller's context."""
    traced = _make_traced(deps.debug)

    @tool
    @traced
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
    @traced
    def set_focus_event(event_query: str) -> str:
        """Switch the focused event to the one matching `event_query` (a name or fragment).
        Subsequent task/reminder/report actions apply to this event."""
        event_id = deps.resolve_event_fn(event_query)
        if not event_id:
            return f"I couldn't find an event matching '{event_query}'."
        deps.session_store.set_current_event(ctx.user_id, event_id)
        msg = f"Focused on '{event_query}'."
        # Option B (Phase 1.9): ground the DM assistant in the event's shared conversation
        # the moment the user focuses — deterministic, no reliance on model judgment. Only
        # in a DM; in a channel the event memory already *is* the live window.
        if ctx.scope == "personal":
            snapshot = deps.event_context_fn(user_id=ctx.user_id, event_id=event_id)
            if snapshot:
                msg = f"{msg}\n\n{snapshot}"
        return msg

    @tool
    @traced
    def prepare_reminders(note: str = "") -> str:
        """Prepare reminders for the members of the currently focused event.
        Optionally pass a `note` to include. Requires a focused event."""
        if not _role_allows(ctx, "moderator"):
            return "You don't have permission to send reminders (needs host or moderator)."
        event_id = deps.session_store.get_current_event(ctx.user_id)
        if not event_id:
            return "No event is focused yet — tell me which event first."
        msg = deps.remind_fn(event_id=event_id, user_id=ctx.user_id, raw=note)
        return msg or "I prepared the reminders — pick a channel on the card above."

    @tool
    @traced
    def list_my_tasks() -> str:
        """List the caller's assigned tasks in the currently focused event."""
        event_id = deps.session_store.get_current_event(ctx.user_id)
        return deps.query_tasks_fn(user_id=ctx.user_id, event_id=event_id)

    @tool
    @traced
    def update_task(task_query: str, status: str) -> str:
        """Update the status of a task in the currently focused event. `task_query` matches
        the task by name; `status` is one of: todo, in_progress, done. You may update your
        own tasks; moderators/hosts may update any. Requires a focused event."""
        event_id = deps.session_store.get_current_event(ctx.user_id)
        if not event_id:
            return "No event is focused yet — tell me which event first."
        return deps.update_task_fn(
            user_id=ctx.user_id, role=ctx.role, event_id=event_id,
            task_query=task_query, status=status,
        )

    @tool
    @traced
    def send_outlook_mail(subject: str, body: str, recipients: list[str] | None = None) -> str:
        """Draft an Outlook email to the focused event's members (or to `recipients` if given).
        Sending is gated by a confirmation card — this only drafts it. Requires host or
        moderator."""
        if not _role_allows(ctx, "moderator"):
            return "You don't have permission to send mail (needs host or moderator)."
        event_id = deps.session_store.get_current_event(ctx.user_id)
        return deps.send_mail_fn(
            user_id=ctx.user_id, event_id=event_id,
            subject=subject, body=body, recipients=recipients,
        )

    @tool
    @traced
    def generate_report() -> str:
        """Generate the AI summary report for the currently focused event."""
        event_id = deps.session_store.get_current_event(ctx.user_id)
        return deps.report_fn(event_id=event_id, user_id=ctx.user_id)

    @tool
    @traced
    def ingest_event_files(link: str = "") -> str:
        """Read the focused event's channel SharePoint files (or a specific SharePoint/OneDrive
        `link` if given), extract members and tasks from them, and propose inviting anyone not
        yet registered. Requires host or moderator and a focused event."""
        if not _role_allows(ctx, "moderator"):
            return "You don't have permission to ingest files (needs host or moderator)."
        event_id = deps.session_store.get_current_event(ctx.user_id)
        if not event_id:
            return "No event is focused yet — tell me which event first."
        return deps.ingest_fn(event_id=event_id, user_id=ctx.user_id, url=link or "")

    @tool
    @traced
    def get_event_context() -> str:
        """Fetch the latest shared discussion, decisions, and open questions from the
        currently focused event. Use when you need up-to-date context about the event the
        user is working on."""
        event_id = deps.session_store.get_current_event(ctx.user_id)
        if not event_id:
            return "No event is focused yet — tell me which event to focus on first."
        snapshot = deps.event_context_fn(user_id=ctx.user_id, event_id=event_id)
        return snapshot or "I don't have any shared discussion recorded for this event yet."

    return [
        create_event, set_focus_event, prepare_reminders,
        list_my_tasks, update_task, send_outlook_mail,
        generate_report, ingest_event_files, get_event_context,
    ]
