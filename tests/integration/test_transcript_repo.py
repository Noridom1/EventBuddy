import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from eventbuddy.agent.transcript import Transcript

pytestmark = pytest.mark.integration


def test_flush_and_rehydrate_roundtrip_against_postgres():
    t = Transcript()  # default session_scope -> real Postgres
    messages = [
        HumanMessage(content="hello", name="Alice"),
        AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "c1"}]),
        ToolMessage(content="tool result", tool_call_id="c1"),
        AIMessage("hi Alice"),
        HumanMessage(content="thanks", name="Alice"),
    ]
    assert t.flush_window("event:itest", messages, event_id="ev-itest") == 3
    # idempotent re-flush
    assert t.flush_window("event:itest", messages) == 0

    out = t.rehydrate("event:itest", budget=4096)
    assert [m.content for m in out] == ["hello", "hi Alice", "thanks"]
    assert isinstance(out[0], HumanMessage) and out[0].name == "Alice"
    assert isinstance(out[1], AIMessage)


def test_rehydrate_budget_keeps_recent_tail():
    t = Transcript(token_counter=lambda text: len(text.split()))
    t.flush_window(
        "dm:itest",
        [HumanMessage("one two three"), AIMessage("four five six"),
         HumanMessage("seven eight"), AIMessage("nine")],
    )
    out = t.rehydrate("dm:itest", budget=4)
    assert [m.content for m in out] == ["seven eight", "nine"]
