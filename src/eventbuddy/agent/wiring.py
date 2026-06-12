from eventbuddy.agent.orchestrator import Orchestrator
from eventbuddy.agent.session import SessionStore
from eventbuddy.data.redis import get_redis


def build_orchestrator() -> Orchestrator:
    """Compose the production orchestrator. Capability fns wrap services within session_scope.
    Live Microsoft actions require credentials; until then create-event still persists locally."""
    session_store = SessionStore(get_redis())

    def provision_fn(**kw):
        from eventbuddy.capabilities.provisioning import ProvisioningService
        from eventbuddy.config import settings
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

    return Orchestrator(
        session_store=session_store, provision_fn=provision_fn,
        resolve_event_fn=resolve_event_fn, remind_fn=remind_fn,
        report_fn=report_fn, query_tasks_fn=query_tasks_fn,
    )
