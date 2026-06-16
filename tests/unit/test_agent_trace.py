"""Impl 10 — agent reasoning trace to the logs.

Two layers: the `TracingCallbackHandler` (driven directly with crafted payloads) and the
runner integration (handler attached via `agent.invoke(config={"callbacks": [...]})` and
exercised through the real `create_react_agent` machinery). Separate from the AGENT_DEBUG
reply footer — the trace lives in the logs, the footer in the reply."""
import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langgraph.checkpoint.memory import InMemorySaver

from eventbuddy.agent.context import RequestContext
from eventbuddy.agent.runner import build_agent_runner
from eventbuddy.agent.tools import AgentDeps, build_tools
from eventbuddy.agent.trace_logger import (
    TRUNCATE_LEN,
    TracingCallbackHandler,
    _render_content,
    _truncate,
)

from .test_tool_tracing import ScriptedChatModel, _FakeSession, _word_counter


def _records(caplog, event):
    return [r for r in caplog.records if getattr(r, "event", None) == event]


# ── handler: llm.input / llm.output ──────────────────────────────────────────────────────
def test_handler_emits_llm_input_output(caplog):
    h = TracingCallbackHandler(thread_id="dm:u1")
    with caplog.at_level(logging.INFO, logger="agent.trace"):
        h.on_chat_model_start(
            {}, [[SystemMessage("you are a bot"), HumanMessage("remind the team")]]
        )
        msg = AIMessage(
            content="I'll list tasks first",
            tool_calls=[{"name": "query_tasks", "args": {}, "id": "c1"}],
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )
        h.on_llm_end(LLMResult(generations=[[ChatGeneration(message=msg)]]))

    inp = _records(caplog, "llm.input")[0]
    assert inp.step == 1
    assert {"role": "system", "content": "you are a bot"} in inp.payload
    assert {"role": "human", "content": "remind the team"} in inp.payload

    out = _records(caplog, "llm.output")[0]
    assert out.step == 1
    assert out.payload["reasoning"] == "I'll list tasks first"
    assert out.payload["tool_calls"] == [{"name": "query_tasks", "args": {}}]
    assert out.usage["total_tokens"] == 15


# ── handler: tool.start / tool.end / tool.error ──────────────────────────────────────────
def test_handler_emits_tool_start_end_error(caplog):
    h = TracingCallbackHandler(thread_id="dm:u1")
    with caplog.at_level(logging.INFO, logger="agent.trace"):
        h.on_tool_start({"name": "query_tasks"}, "{}")
        h.on_tool_end(ToolMessage(content="3 open tasks", tool_call_id="c1"))
        h.on_tool_error(ValueError("bad arg"))

    assert _records(caplog, "tool.start")[0].tool == "query_tasks"
    assert _records(caplog, "tool.end")[0].payload == "3 open tasks"
    assert "ValueError: bad arg" in _records(caplog, "tool.error")[0].payload


# ── truncation + image redaction ─────────────────────────────────────────────────────────
def test_truncation_and_image_redaction():
    long = "x" * (TRUNCATE_LEN + 500)
    cut = _truncate(long)
    assert cut.startswith("x" * TRUNCATE_LEN)
    assert "(+500 chars)" in cut

    multimodal = [
        {"type": "text", "text": "describe this"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA…huge…"}},
    ]
    rendered = _render_content(multimodal)
    assert "describe this" in rendered
    assert "<image>" in rendered
    assert "base64" not in rendered


# ── observability must never break a turn ────────────────────────────────────────────────
def test_handler_never_raises(caplog):
    h = TracingCallbackHandler(thread_id="dm:u1")
    with caplog.at_level(logging.INFO, logger="agent.trace"):
        # Malformed payloads: messages not a list-of-lists, response without generations.
        h.on_chat_model_start({}, "not-a-list")          # must not raise
        h.on_llm_end(object())                            # must not raise
    # Each degraded to an emitted record carrying a trace-error marker, not an exception.
    assert _records(caplog, "llm.input")
    assert _records(caplog, "llm.output")


# ── runner integration: handler attached only when trace=True ────────────────────────────
def _deps():
    return AgentDeps(
        session_store=_FakeSession(),
        provision_fn=lambda **kw: type("E", (), {"event_id": "ev-1"})(),
        resolve_event_fn=lambda q, **kw: "ev-7",
        remind_fn=lambda **kw: None,
        report_fn=lambda **kw: "report",
        query_tasks_fn=lambda **kw: "3 open tasks",
        debug=False,
    )


def _runner(model, *, trace):
    return build_agent_runner(
        model,
        tools_factory=lambda ctx: build_tools(_deps(), ctx),
        checkpointer=InMemorySaver(),
        token_counter=_word_counter,
        trace=trace,
    )


def _query_tasks_call():
    return AIMessage(
        content="checking the board",
        tool_calls=[{"name": "list_my_tasks", "args": {}, "id": "c1"}],
    )


def test_runner_attaches_handler_when_trace_on(caplog):
    model = ScriptedChatModel(responses=[_query_tasks_call(), AIMessage("You have 3 tasks.")])
    with caplog.at_level(logging.INFO, logger="agent.trace"):
        reply = _runner(model, trace=True).run(
            "what's on the board?", RequestContext(user_id="u1", role="host")
        )
    assert reply == "You have 3 tasks."
    events = {getattr(r, "event", None) for r in caplog.records}
    assert {"turn.start", "llm.input", "llm.output", "tool.start", "tool.end"} <= events
    # the trace captured the tool's RETURN value — the piece the footer never had
    assert any("3 open tasks" in str(getattr(r, "payload", "")) for r in caplog.records)


def test_runner_no_trace_when_off(caplog):
    model = ScriptedChatModel(responses=[AIMessage("just chatting")])
    with caplog.at_level(logging.INFO, logger="agent.trace"):
        _runner(model, trace=False).run("hi", RequestContext(user_id="u1", role="host"))
    assert not [r for r in caplog.records if getattr(r, "event", None)]


# ── trace is independent of the AGENT_DEBUG footer ───────────────────────────────────────
def test_trace_independent_of_debug(caplog):
    """trace on + debug off → log records, no reply footer."""
    model = ScriptedChatModel(responses=[_query_tasks_call(), AIMessage("done")])
    with caplog.at_level(logging.INFO, logger="agent.trace"):
        reply = _runner(model, trace=True).run(
            "go", RequestContext(user_id="u1", role="host")
        )
    assert "debug · tool calls" not in reply        # no footer (debug=False)
    assert _records(caplog, "llm.output")           # but the trace fired
