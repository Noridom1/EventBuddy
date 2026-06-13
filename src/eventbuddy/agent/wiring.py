from langchain_core.messages import HumanMessage

from eventbuddy.agent.orchestrator import Orchestrator
from eventbuddy.agent.session import SessionStore
from eventbuddy.common.logging import get_logger
from eventbuddy.config import settings
from eventbuddy.data.redis import get_redis

log = get_logger("agent.wiring")

# A DM-injected event snapshot competes with the user's own turns for the 4096-token DM
# window, so keep the cross-context read compact (Phase 1.9, Part B).
EVENT_CTX_BUDGET = 700


def _build_event_context_fn(transcript, summarizer):
    """The single guarded DM→event cross-context read (Phase 1.9, Part B). Owns all three
    security checks (cross-cutting rule 2 + one-directional privacy) in one place:

      1. event id is always the *server-resolved* focused event — never a tool argument;
      2. membership is verified server-side (non-member → empty, not an error);
      3. only the event thread's L3 summary + L2 transcript tail are read — never L1, and
         never the reverse direction (an event channel never reads a user's DM).

    Returns a compact, timestamped snapshot string, or "" on any miss (no focused event /
    no channel bound / not a member / nothing recorded) — graceful, consistent with the
    rest of the system."""
    from eventbuddy.agent.context import event_thread_id
    from eventbuddy.agent.transcript import sent_at_prefix

    def event_context_fn(*, user_id: str, event_id: str | None) -> str:
        if not event_id:
            return ""
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.events import EventRepository
        from eventbuddy.data.repositories.members import MemberRepository
        try:
            with session_scope() as s:
                ev = EventRepository(s).get(event_id)
                if ev is None or ev.teams_channel_id is None:
                    return ""  # no shared thread to read
                if MemberRepository(s).get_by_user(event_id, user_id) is None:
                    return ""  # not a member — don't leak the shared conversation
                thread_id = event_thread_id(ev.teams_channel_id)
                event_name = ev.event_name
        except Exception as e:  # noqa: BLE001 — degrade gracefully, never break the turn
            log.warning(f"event context read failed ({type(e).__name__}: {e})")
            return ""

        summary = summarizer.get_summary(thread_id) if summarizer is not None else ""
        tail = (
            transcript.rehydrate(thread_id, budget=EVENT_CTX_BUDGET)
            if transcript is not None
            else []
        )
        if not summary and not tail:
            return ""

        parts = [f"Context from event '{event_name}':"]
        if summary:
            parts.append(summary)
        if tail:
            parts.append("\nRecent discussion:")
            for m in tail:
                role = "User" if isinstance(m, HumanMessage) else "Assistant"
                speaker = getattr(m, "name", None)
                who = f"{role} ({speaker})" if speaker else role
                parts.append(f"{sent_at_prefix(m)}{who}: {m.content}")
        return "\n".join(parts)

    return event_context_fn


def build_orchestrator() -> Orchestrator:
    """Compose the production orchestrator. Phase 1.7 routes the conversation through an
    LLM tool-calling runner (create_react_agent + layered memory); the same capability
    closures remain the tool bodies (DRY). Without MaaS creds — or with agent_mode=regex —
    it degrades to the Phase 1 regex router. Live Microsoft actions still require Graph
    credentials; until then create-event persists locally."""
    session_store = SessionStore(get_redis())

    def provision_fn(**kw):
        from eventbuddy.capabilities.provisioning import ProvisioningService
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.events import EventRepository
        from eventbuddy.data.repositories.members import MemberRepository
        from eventbuddy.integrations.graph.client import GraphClient
        from eventbuddy.integrations.graph.token import MsalTokenProvider
        with session_scope() as s:
            svc = ProvisioningService(
                EventRepository(s), MemberRepository(s),
                GraphClient(MsalTokenProvider()), team_id=settings.microsoft_app_tenant_id,
            )
            ev = svc.create_event(**kw)
            s.flush()
            return type("E", (), {"event_id": ev.event_id})()

    def resolve_event_fn(query: str) -> str | None:
        from sqlalchemy import select

        from eventbuddy.data.db import session_scope
        from eventbuddy.domain.models import Event
        with session_scope() as s:
            ev = s.scalar(select(Event).where(Event.event_name.ilike(f"%{query}%")))
            return ev.event_id if ev else None

    def remind_fn(**kw):
        return None  # HITL card flow handled by activity_router; placeholder service hook

    def report_fn(*, event_id):
        return "Report generation is available in Phase 1.5."

    def query_tasks_fn(*, user_id, event_id):
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.tasks import TaskRepository
        with session_scope() as s:
            tasks = TaskRepository(s).by_assignee(user_id)
            if not tasks:
                return "You have no assigned tasks."
            return "Your tasks:\n" + "\n".join(f"- {t.task_name} ({t.status})" for t in tasks)

    runner, summarizer = _build_runner_and_summarizer(
        session_store, provision_fn, resolve_event_fn, remind_fn, report_fn, query_tasks_fn
    )

    orch = Orchestrator(
        session_store=session_store, provision_fn=provision_fn,
        resolve_event_fn=resolve_event_fn, remind_fn=remind_fn,
        report_fn=report_fn, query_tasks_fn=query_tasks_fn,
        runner=runner, agent_mode=settings.agent_mode if runner else "regex",
        regex_fallback_on_error=not settings.agent_debug,
    )
    orch.summarizer = summarizer  # exposed so main.py can schedule the consolidation job
    return orch


def build_summarizer():
    """The rolling-summary consolidator, or None without MaaS creds. Stateless aside from
    its LLM/DB handles — safe to build standalone for the background scheduler job."""
    from eventbuddy.agent.summarizer import Summarizer
    from eventbuddy.integrations.llm.client import LLMGateway

    return Summarizer(LLMGateway()) if settings.agentbase_llm_base_url else None


def _build_runner_and_summarizer(
    session_store, provision_fn, resolve_event_fn, remind_fn, report_fn, query_tasks_fn
):
    """Build the LLM runner + summarizer, or (None, summarizer) when the chat path can't run
    (no creds / agent_mode=regex). The summarizer is built regardless so the background
    consolidation job can run wherever a transcript exists."""
    summarizer = build_summarizer()

    creds = bool(settings.agentbase_llm_base_url and settings.agentbase_llm_api_key)
    if settings.agent_mode != "llm" or not creds:
        if not creds:
            log.info("No MaaS creds — chat path degraded to the regex router.")
        return None, summarizer

    from eventbuddy.agent.memory import build_checkpointer, setup_checkpointer
    from eventbuddy.agent.model import build_chat_model, make_token_counter
    from eventbuddy.agent.runner import build_agent_runner
    from eventbuddy.agent.tools import AgentDeps, build_tools
    from eventbuddy.agent.transcript import Transcript

    model = build_chat_model()
    checkpointer = build_checkpointer()
    setup_checkpointer(checkpointer)
    transcript = Transcript()

    # Built here (after transcript + summarizer exist) so the cross-context closure can
    # close over them — same DRY composition-root pattern as the other capability closures.
    event_context_fn = _build_event_context_fn(transcript, summarizer)

    deps = AgentDeps(
        session_store=session_store, provision_fn=provision_fn,
        resolve_event_fn=resolve_event_fn, remind_fn=remind_fn,
        report_fn=report_fn, query_tasks_fn=query_tasks_fn,
        event_context_fn=event_context_fn,
        debug=settings.agent_debug,
    )
    runner = build_agent_runner(
        model,
        tools_factory=lambda ctx: build_tools(deps, ctx),
        checkpointer=checkpointer,
        token_counter=make_token_counter(),
        transcript=transcript,
        summarizer=summarizer,
        debug=settings.agent_debug,
    )
    return runner, summarizer
