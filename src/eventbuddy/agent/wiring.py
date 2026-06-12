from eventbuddy.agent.orchestrator import Orchestrator
from eventbuddy.agent.session import SessionStore
from eventbuddy.common.logging import get_logger
from eventbuddy.config import settings
from eventbuddy.data.redis import get_redis

log = get_logger("agent.wiring")


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

    deps = AgentDeps(
        session_store=session_store, provision_fn=provision_fn,
        resolve_event_fn=resolve_event_fn, remind_fn=remind_fn,
        report_fn=report_fn, query_tasks_fn=query_tasks_fn,
    )
    runner = build_agent_runner(
        model,
        tools_factory=lambda ctx: build_tools(deps, ctx),
        checkpointer=checkpointer,
        token_counter=make_token_counter(),
        transcript=transcript,
        summarizer=summarizer,
    )
    return runner, summarizer
