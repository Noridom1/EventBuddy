"""Phase 1.8 — transparent tool-use errors.

The LLM agent no longer silently degrades to regex on a runtime error: in debug mode the
reply carries a footer listing every tool call this turn (name + params) with the full
exception + traceback for any that failed. With debug off, today's silent regex fallback
is preserved."""
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from eventbuddy.agent.context import RequestContext
from eventbuddy.agent.orchestrator import Orchestrator
from eventbuddy.agent.runner import build_agent_runner
from eventbuddy.agent.tools import AgentDeps, build_tools


class ScriptedChatModel(BaseChatModel):
    """Returns preset AIMessages in order, ignoring inputs. Supports bind_tools so it can
    drive create_react_agent's tool loop without a live model."""

    responses: list
    idx: int = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        msg = self.responses[self.idx]
        self.idx += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self) -> str:
        return "scripted"


class ExplodingChatModel(BaseChatModel):
    """Raises on the first model call — simulates a loop/infra error (no model reply)."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        raise RuntimeError("MaaS endpoint unreachable")

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self) -> str:
        return "exploding"


class _FakeSession:
    def __init__(self):
        self.current = {}

    def set_current_event(self, user_id, event_id):
        self.current[user_id] = event_id

    def get_current_event(self, user_id):
        return self.current.get(user_id)


def _word_counter(messages):
    return sum(len(str(m.content).split()) for m in messages)


def _deps(*, debug, provision_fn=None):
    def _ok_provision(**kw):
        return type("E", (), {"event_id": "ev-1"})()

    return AgentDeps(
        session_store=_FakeSession(),
        provision_fn=provision_fn or _ok_provision,
        resolve_event_fn=lambda q: "ev-7",
        remind_fn=lambda **kw: None,
        report_fn=lambda **kw: "report",
        query_tasks_fn=lambda **kw: "tasks",
        debug=debug,
    )


def _create_event_call():
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "create_event",
            "args": {"name": "Launch Party", "member_emails": ["a@x.com"]},
            "id": "call-1",
        }],
    )


def _runner(model, deps, **kw):
    return build_agent_runner(
        model,
        tools_factory=lambda ctx: build_tools(deps, ctx),
        checkpointer=InMemorySaver(),
        token_counter=_word_counter,
        debug=deps.debug,
        **kw,
    )


def _boom(**kw):
    raise ValueError("Your given address (https://login.microsoftonline.com/) is invalid")


# ── 1. tool error → footer with name + params + traceback ────────────────────────────────
def test_tool_error_surfaced_in_footer():
    deps = _deps(debug=True, provision_fn=_boom)
    model = ScriptedChatModel(responses=[_create_event_call(), AIMessage("I hit a snag.")])
    reply = _runner(model, deps).run("create Launch Party with a@x.com",
                                     RequestContext(user_id="u1", role="host"))
    assert "I hit a snag." in reply              # model still replies
    assert "✗ create_event(" in reply            # the failing tool, marked
    assert "name='Launch Party'" in reply        # the params it passed
    assert "a@x.com" in reply
    assert "ValueError" in reply
    assert "Traceback" in reply                  # full traceback


# ── 2. successful tool calls are listed (params visible, no traceback) ───────────────────
def test_successful_tool_calls_listed():
    deps = _deps(debug=True)
    model = ScriptedChatModel(responses=[_create_event_call(), AIMessage("Created it!")])
    reply = _runner(model, deps).run("create Launch Party with a@x.com",
                                     RequestContext(user_id="u1", role="host"))
    assert "Created it!" in reply
    assert "✓ create_event(" in reply
    assert "Traceback" not in reply


# ── 3. pure chat turn → no footer ────────────────────────────────────────────────────────
def test_no_footer_when_no_tools_called():
    deps = _deps(debug=True)
    model = ScriptedChatModel(responses=[AIMessage("Just chatting, no tools.")])
    reply = _runner(model, deps).run("hello", RequestContext(user_id="u1", role="host"))
    assert reply == "Just chatting, no tools."
    assert "debug · tool calls" not in reply


# ── 4. debug off preserves the silent regex fallback (degradation contract) ──────────────
class _RaisingRunner:
    def run(self, text, ctx):
        raise ValueError("boom in the loop")


def test_debug_off_preserves_regex_fallback():
    orch = Orchestrator(
        session_store=_FakeSession(),
        provision_fn=lambda **kw: type("E", (), {"event_id": "ev-9"})(),
        resolve_event_fn=lambda q: "ev-7",
        remind_fn=lambda **kw: None, report_fn=lambda **kw: "report",
        query_tasks_fn=lambda **kw: "tasks",
        runner=_RaisingRunner(), regex_fallback_on_error=True,
    )
    out = orch.handle(user_id="u1", channel_id=None,
                      text="create event 'Launch' members: a@x.com")
    assert "Created event 'Launch'" in out        # regex router answered
    assert "[agent error]" not in out


def test_debug_on_orchestrator_surfaces_error_instead_of_regex():
    orch = Orchestrator(
        session_store=_FakeSession(),
        provision_fn=lambda **kw: type("E", (), {"event_id": "ev-9"})(),
        resolve_event_fn=lambda q: "ev-7",
        remind_fn=lambda **kw: None, report_fn=lambda **kw: "report",
        query_tasks_fn=lambda **kw: "tasks",
        runner=_RaisingRunner(), regex_fallback_on_error=False,
    )
    out = orch.handle(user_id="u1", channel_id=None,
                      text="create event 'Launch' members: a@x.com")
    assert "[agent error]" in out
    assert "boom in the loop" in out
    assert "Created event 'Launch'" not in out    # regex did NOT run


# ── 5. loop/infra error → debug block with traceback (no regex) ──────────────────────────
def test_loop_error_returns_debug_block():
    deps = _deps(debug=True)
    reply = _runner(ExplodingChatModel(), deps).run(
        "hello", RequestContext(user_id="u1", role="host"))
    assert "[agent error]" in reply
    assert "RuntimeError" in reply
    assert "MaaS endpoint unreachable" in reply
    assert "Traceback" in reply


def test_loop_error_reraises_when_debug_off():
    deps = _deps(debug=False)
    runner = _runner(ExplodingChatModel(), deps)
    try:
        runner.run("hello", RequestContext(user_id="u1", role="host"))
        raise AssertionError("expected the loop error to propagate when debug is off")
    except RuntimeError as e:
        assert "MaaS endpoint unreachable" in str(e)


# ── 6. footer never leaks server-side identity (cross-cutting rule 2) ────────────────────
def test_params_exclude_identity():
    deps = _deps(debug=True, provision_fn=_boom)
    model = ScriptedChatModel(responses=[_create_event_call(), AIMessage("snag")])
    reply = _runner(model, deps).run("create Launch Party with a@x.com",
                                     RequestContext(user_id="secret-user", role="host"))
    assert "host_user_id" not in reply
    assert "secret-user" not in reply
    assert "user_id=" not in reply
    assert "role=" not in reply


# ── 7. trace is isolated per request (no bleed between runs) ──────────────────────────────
def test_trace_contextvar_isolated():
    deps = _deps(debug=True)
    runner = _runner(
        ScriptedChatModel(responses=[
            _create_event_call(), AIMessage("first done"),  # run 1: a tool call
            AIMessage("second, no tools"),                  # run 2: pure chat
        ]),
        deps,
    )
    ctx = RequestContext(user_id="u1", role="host")
    runner.run("create Launch Party with a@x.com", ctx)
    second = runner.run("just chatting now", ctx)
    assert second == "second, no tools"        # run 2 carries no footer at all
    assert "create_event" not in second        # run 1's record did not bleed in
