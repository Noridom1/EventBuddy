"""Live end-to-end smoke for the Phase 1.7 tool-calling agent.

Gated: skipped unless real MaaS creds are present. Needs local Postgres + Redis (from
docker-compose) with migration 0002 applied. Microsoft Graph is mocked (no live Teams);
the database is real, so we assert the create_event tool actually persisted an event and
that the Redis checkpointer carried conversation history across two turns.
"""
import pytest
from sqlalchemy import select

from eventbuddy.agent.context import RequestContext
from eventbuddy.agent.memory import build_checkpointer, setup_checkpointer
from eventbuddy.agent.model import build_chat_model
from eventbuddy.agent.runner import build_agent_runner
from eventbuddy.agent.tools import AgentDeps, build_tools
from eventbuddy.agent.transcript import Transcript
from eventbuddy.config import settings
from eventbuddy.data.db import session_scope
from eventbuddy.domain.models import Event

pytestmark = pytest.mark.integration

_HAS_CREDS = bool(settings.agentbase_llm_base_url and settings.agentbase_llm_api_key)
skip_no_creds = pytest.mark.skipif(not _HAS_CREDS, reason="no live MaaS creds")


class _FakeGraph:
    def create_channel(self, team_id, display_name, description=""):
        return {"id": f"chan-{display_name}"}


def _provision_fn(**kw):
    from eventbuddy.capabilities.provisioning import ProvisioningService
    from eventbuddy.data.repositories.events import EventRepository
    from eventbuddy.data.repositories.members import MemberRepository

    with session_scope() as s:
        svc = ProvisioningService(
            EventRepository(s), MemberRepository(s), _FakeGraph(), team_id="smoke-team"
        )
        ev = svc.create_event(**kw)
        s.flush()
        return type("E", (), {"event_id": ev.event_id})()


class _Session:
    def __init__(self):
        self.current = {}

    def get_current_event(self, user_id):
        return self.current.get(user_id)

    def set_current_event(self, user_id, event_id):
        self.current[user_id] = event_id

    def clear_current_event(self, user_id):
        self.current.pop(user_id, None)


def _runner_and_checkpointer():
    deps = AgentDeps(
        session_store=_Session(),
        provision_fn=_provision_fn,
        resolve_event_fn=lambda q: None,
        remind_fn=lambda **kw: None,
        report_fn=lambda **kw: "report",
        query_tasks_fn=lambda **kw: "no tasks",
    )
    checkpointer = build_checkpointer()
    setup_checkpointer(checkpointer)
    runner = build_agent_runner(
        build_chat_model(),
        tools_factory=lambda ctx: build_tools(deps, ctx),
        checkpointer=checkpointer,
        transcript=Transcript(),
    )
    return runner, checkpointer


@skip_no_creds
def test_create_event_tool_fires_and_persists():
    runner, _ = _runner_and_checkpointer()
    ctx = RequestContext(user_id="smoke-user", role="host", scope="personal")
    runner.run("create an event called Smoke Test with members a@x.com", ctx)

    with session_scope() as s:
        ev = s.scalar(select(Event).where(Event.event_name == "Smoke Test"))
    assert ev is not None


@skip_no_creds
def test_memory_carries_across_turns():
    runner, checkpointer = _runner_and_checkpointer()
    ctx = RequestContext(user_id="smoke-mem", role="host", scope="personal")
    runner.run("My favourite colour is teal. Remember it.", ctx)
    runner.run("What is my favourite colour?", ctx)

    state = checkpointer.get_tuple({"configurable": {"thread_id": "dm:smoke-mem"}})
    assert state is not None
    messages = state.checkpoint["channel_values"]["messages"]
    assert len(messages) >= 4  # two user turns + two assistant turns carried in the window
