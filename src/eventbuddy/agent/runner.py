"""Agent runner — the brain. One factory hides the Path-A (native tool calling) vs
Path-B (structured JSON) mechanic behind `.run(text, ctx) -> reply`. Everything else in
the system talks to this object, not to LangGraph directly.

Path A (the spike-selected default, 2026-06-12): `create_react_agent` runs the tool loop;
a Redis checkpointer holds the working window; a `pre_model_hook` trims it to <=4096 tokens
on user/assistant boundaries so no tool-call/result pair is ever orphaned."""
import traceback
from collections.abc import Callable

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, trim_messages
from langgraph.prebuilt import ToolNode, create_react_agent

from eventbuddy.agent.context import RequestContext
from eventbuddy.agent.prompts import system_prompt
from eventbuddy.agent.tools import ToolCallRecord, begin_trace, end_trace

MAX_TOKENS = 4096
RECURSION_LIMIT = 8


def _format_params(params: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in params.items())


def _format_footer(records: list[ToolCallRecord]) -> str:
    """The Phase 1.8 debug footer: every tool call this turn (name + params), with the
    exception + traceback for any that failed. Deterministic separator so it's easy to
    strip/match in tests and downstream tooling."""
    lines = [f"──────── debug · tool calls ({len(records)}) ────────"]
    for r in records:
        mark = "✓" if r.ok else "✗"
        lines.append(f"{mark} {r.tool}({_format_params(r.params)})")
        if not r.ok:
            lines.append(f"    {r.error}")
            if r.traceback:
                lines.append("\n".join(f"    {ln}" for ln in r.traceback.rstrip().splitlines()))
    return "\n".join(lines)


def _format_error_block(tb: str, records: list[ToolCallRecord]) -> str:
    """Surfaced when the loop itself errors out (no model reply produced): the traceback,
    plus any tool calls captured before the crash."""
    block = "[agent error]\n" + "\n".join(f"    {ln}" for ln in tb.rstrip().splitlines())
    if records:
        block = f"{block}\n\n{_format_footer(records)}"
    return block


def make_trimmer(token_counter, max_tokens: int = MAX_TOKENS) -> Callable:
    """Build a `pre_model_hook` that trims the working window to `max_tokens`, cutting
    ONLY on user/assistant boundaries (`start_on="human"`) so a `tool_call_id` is never
    orphaned — orphaning one makes the OpenAI/MaaS API reject the request."""

    def pre_model_hook(state: dict) -> dict:
        messages = state["messages"]
        trimmed = trim_messages(
            messages,
            max_tokens=max_tokens,
            token_counter=token_counter,
            strategy="last",
            start_on="human",
            include_system=False,
            allow_partial=False,
        )
        if not trimmed:  # last turn alone exceeds budget — keep it rather than send nothing
            trimmed = messages[-1:]
        return {"llm_input_messages": trimmed}

    return pre_model_hook


class AgentRunner:
    """Path-A runner. The model + checkpointer are shared singletons; tools and prompt are
    rebuilt per request to bind the caller's `RequestContext` (cheap — just graph assembly)."""

    def __init__(
        self,
        *,
        model,
        tools_factory: Callable[[RequestContext], list],
        checkpointer,
        prompt_fn: Callable[[RequestContext], str] = system_prompt,
        token_counter=None,
        recursion_limit: int = RECURSION_LIMIT,
        max_tokens: int = MAX_TOKENS,
        transcript=None,
        summarizer=None,
        debug: bool = False,
    ):
        self._model = model
        self._tools_factory = tools_factory
        self._checkpointer = checkpointer
        self._prompt_fn = prompt_fn
        self._recursion_limit = recursion_limit
        self._pre_model_hook = make_trimmer(token_counter or model, max_tokens)
        self._transcript = transcript
        self._summarizer = summarizer
        self._debug = debug

    def _config(self, ctx: RequestContext) -> dict:
        return {
            "configurable": {"thread_id": ctx.thread_id},
            "recursion_limit": self._recursion_limit,
        }

    def _seed_messages(self, ctx: RequestContext) -> list[BaseMessage]:
        """When the Redis working window is empty (TTL expired / evicted), seed initial
        state from the rolling summary + the durable transcript tail."""
        seed: list[BaseMessage] = []
        if self._summarizer is not None:
            summary = self._summarizer.get_summary(ctx.thread_id)
            if summary:
                seed.append(SystemMessage(content=f"Summary of earlier conversation: {summary}"))
        if self._transcript is not None:
            seed.extend(self._transcript.rehydrate(ctx.thread_id))
        return seed

    def _window_empty(self, config: dict) -> bool:
        try:
            return self._checkpointer.get_tuple(config) is None
        except Exception:
            return True

    def reset(self, thread_id: str) -> None:
        """Drop a thread's working window (dev convenience / fresh conversation)."""
        delete = getattr(self._checkpointer, "delete_thread", None)
        if delete is not None:
            try:
                delete(thread_id)
            except Exception:  # noqa: BLE001
                pass

    def run(self, text: str, ctx: RequestContext) -> str:
        # `handle_tool_errors=False` so a raising tool body propagates instead of being
        # swallowed by the ToolNode — our `_traced` wrapper already owns error behavior
        # (soft-string + record in debug, re-raise otherwise). Phase 1.8.
        agent = create_react_agent(
            self._model,
            ToolNode(self._tools_factory(ctx), handle_tool_errors=False),
            prompt=self._prompt_fn(ctx),
            checkpointer=self._checkpointer,
            pre_model_hook=self._pre_model_hook,
        )
        config = self._config(ctx)
        messages: list[BaseMessage] = []
        if (self._transcript is not None or self._summarizer is not None) and self._window_empty(
            config
        ):
            messages.extend(self._seed_messages(ctx))
        messages.append(ctx.tag(text))

        trace, token = begin_trace()
        try:
            result = agent.invoke({"messages": messages}, config=config)
            final = result["messages"][-1]
            reply = final.content if isinstance(final, AIMessage) else str(final.content)
            if self._debug and trace.records:
                reply = f"{reply}\n\n{_format_footer(trace.records)}"
            return reply
        except Exception:
            # Loop/infra error (LLM call, recursion limit, or a tool re-raised). In debug,
            # surface it instead of letting the orchestrator silently fall back to regex.
            if self._debug:
                return _format_error_block(traceback.format_exc(), trace.records)
            raise
        finally:
            end_trace(token)


def build_agent_runner(
    model,
    *,
    tools_factory: Callable[[RequestContext], list],
    checkpointer,
    prompt_fn: Callable[[RequestContext], str] = system_prompt,
    token_counter=None,
    transcript=None,
    summarizer=None,
    debug: bool = False,
) -> AgentRunner:
    """Compose the Path-A agent runner. `tools_factory(ctx)` rebuilds the tool set bound to
    the request; `transcript`/`summarizer` (optional) enable empty-window rehydration.
    `debug` turns on the Phase 1.8 tool-trace footer + error surfacing (no regex fallback)."""
    return AgentRunner(
        model=model,
        tools_factory=tools_factory,
        checkpointer=checkpointer,
        prompt_fn=prompt_fn,
        token_counter=token_counter,
        transcript=transcript,
        summarizer=summarizer,
        debug=debug,
    )
