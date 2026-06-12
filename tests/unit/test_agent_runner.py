from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from eventbuddy.agent.context import RequestContext
from eventbuddy.agent.runner import build_agent_runner, make_trimmer
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


class _FakeSession:
    def __init__(self):
        self.current = {}

    def set_current_event(self, user_id, event_id):
        self.current[user_id] = event_id

    def get_current_event(self, user_id):
        return self.current.get(user_id)


def _deps(calls):
    def provision_fn(**kw):
        calls["provision"] = kw
        return type("E", (), {"event_id": "ev-1"})()

    return AgentDeps(
        session_store=_FakeSession(),
        provision_fn=provision_fn,
        resolve_event_fn=lambda q: "ev-7",
        remind_fn=lambda **kw: None,
        report_fn=lambda **kw: "report",
        query_tasks_fn=lambda **kw: "tasks",
    )


def _word_counter(messages):
    return sum(len(str(m.content).split()) for m in messages)


def test_run_drives_tool_then_returns_grounded_reply():
    calls = {}
    deps = _deps(calls)
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "create_event",
                        "args": {"name": "Smoke Test", "member_emails": ["a@x.com"]},
                        "id": "call-1",
                    }
                ],
            ),
            AIMessage(content="Done — created 'Smoke Test'."),
        ]
    )
    runner = build_agent_runner(
        model,
        tools_factory=lambda ctx: build_tools(deps, ctx),
        checkpointer=InMemorySaver(),
        token_counter=_word_counter,
    )
    reply = runner.run("create an event called Smoke Test with a@x.com",
                       RequestContext(user_id="leader", role="host"))
    assert calls["provision"]["name"] == "Smoke Test"
    assert calls["provision"]["host_user_id"] == "leader"
    assert reply == "Done — created 'Smoke Test'."


def test_thread_id_is_scope_aware():
    assert RequestContext(user_id="u1").thread_id == "dm:u1"
    assert RequestContext(user_id="u1", channel_id="ch9", scope="channel").thread_id == "event:ch9"


def test_trimmer_cuts_on_human_boundary_without_orphaning_tool_pair():
    # An old tool-call/result pair followed by recent user/assistant turns. Trimming must
    # not leave a ToolMessage as the first kept message (orphaned tool_call_id).
    history = [
        HumanMessage("please " * 50),
        AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "c1"}]),
        ToolMessage(content="result " * 50, tool_call_id="c1"),
        AIMessage("ok " * 50),
        HumanMessage("recent question"),
        AIMessage("recent answer"),
    ]
    hook = make_trimmer(_word_counter, max_tokens=10)
    trimmed = hook({"messages": history})["llm_input_messages"]
    assert isinstance(trimmed[0], HumanMessage)
    # no ToolMessage may appear without its triggering AIMessage tool_call before it
    ids_called = {tc["id"] for m in trimmed if isinstance(m, AIMessage) for tc in m.tool_calls}
    for m in trimmed:
        if isinstance(m, ToolMessage):
            assert m.tool_call_id in ids_called


def test_trimmer_keeps_last_turn_when_over_budget():
    history = [HumanMessage("a " * 100)]
    hook = make_trimmer(_word_counter, max_tokens=5)
    trimmed = hook({"messages": history})["llm_input_messages"]
    assert len(trimmed) == 1
