"""Impl 10 — agent reasoning trace, emitted to the logs.

A `TracingCallbackHandler` is attached (per turn) to `agent.invoke(config={"callbacks": [...]})`
when `AGENT_TRACE=true`. LangGraph propagates the callback to the chat model and the tool
node, so every step of the ReAct loop becomes an ordered, structured log line under the
`agent.trace` logger at INFO — without touching tool bodies or the agent construction:

    turn.start → llm.input → llm.output → tool.start → tool.end → llm.input → …

Each line carries structured fields (`event`, `thread_id`, `step`, `payload`, …) serialized
by `_JSONFormatter` (see common/logging.py), so a turn is `jq`-filterable:

    ... | jq 'select(.logger=="agent.trace")'

This is SEPARATE from the `AGENT_DEBUG` reply footer (`ToolTrace`): that appends tool
name+params to the user reply; this writes the full input/reasoning/return to the logs.
Observability must never break a turn, so every hook is defensively wrapped — a formatting
error degrades to a single warning, never an exception into the loop."""
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from eventbuddy.common.logging import get_logger

log = get_logger("agent.trace")

# Cap each rendered message / tool payload so a turn can't dump full file contents or a
# base64 image into the log. Cut strings get a "…(+N chars)" marker.
TRUNCATE_LEN = 2000


def _truncate(text: str, limit: int = TRUNCATE_LEN) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…(+{len(text) - limit} chars)"


def _render_content(content: Any) -> str:
    """Render a message's content for the trace. LangChain content is either a plain string
    or a list of parts (multimodal); a base64 `image_url` part is redacted to `<image>` so the
    blob never lands in the log. Text parts pass through (truncated by the caller)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                ptype = part.get("type")
                if ptype == "text":
                    parts.append(str(part.get("text", "")))
                elif ptype == "image_url":
                    parts.append("<image>")
                else:
                    parts.append(f"<{ptype or 'part'}>")
            else:
                parts.append(str(part))
        return " ".join(parts)
    return str(content)


def _message_role(message: Any) -> str:
    """Best-effort role label for a LangChain message (HumanMessage → 'human', etc.)."""
    return getattr(message, "type", None) or type(message).__name__


class TracingCallbackHandler(BaseCallbackHandler):
    """Per-turn handler. One instance per `runner.run(...)`; `step` counts LLM rounds so the
    trace reads as an ordered sequence. All emits are at INFO under `agent.trace`."""

    def __init__(self, *, thread_id: str) -> None:
        self._thread_id = thread_id
        self._step = 0

    def _emit(self, event: str, **fields: Any) -> None:
        try:
            log.info(event, extra={"event": event, "thread_id": self._thread_id, **fields})
        except Exception as e:  # noqa: BLE001 — tracing must never break a turn
            log.warning(f"agent.trace emit failed ({type(e).__name__}: {e})")

    def on_chat_model_start(self, serialized, messages, **kwargs) -> None:
        try:
            self._step += 1
            # `messages` is a list of prompts (one per generation); the agent sends one.
            rendered = [
                {"role": _message_role(m), "content": _truncate(_render_content(m.content))}
                for m in (messages[0] if messages else [])
            ]
            self._emit("llm.input", step=self._step, payload=rendered)
        except Exception as e:  # noqa: BLE001
            self._emit("llm.input", step=self._step, payload=f"<trace error: {e}>")

    def on_llm_end(self, response, **kwargs) -> None:
        try:
            gen = response.generations[0][0]
            message = getattr(gen, "message", None)
            content = _render_content(getattr(message, "content", "")) if message else ""
            tool_calls = [
                {"name": tc.get("name"), "args": tc.get("args")}
                for tc in (getattr(message, "tool_calls", None) or [])
            ]
            usage = getattr(message, "usage_metadata", None) if message else None
            self._emit(
                "llm.output", step=self._step,
                payload={"reasoning": _truncate(content), "tool_calls": tool_calls},
                usage=usage,
            )
        except Exception as e:  # noqa: BLE001
            self._emit("llm.output", step=self._step, payload=f"<trace error: {e}>")

    def on_tool_start(self, serialized, input_str, **kwargs) -> None:
        name = (serialized or {}).get("name", "tool")
        self._emit("tool.start", step=self._step, tool=name,
                   payload=_truncate(str(input_str)))

    def on_tool_end(self, output, **kwargs) -> None:
        # `output` is usually a ToolMessage; fall back to str() for anything else.
        content = getattr(output, "content", output)
        self._emit("tool.end", step=self._step, payload=_truncate(_render_content(content)))

    def on_tool_error(self, error, **kwargs) -> None:
        self._emit("tool.error", step=self._step,
                   payload=f"{type(error).__name__}: {error}")
