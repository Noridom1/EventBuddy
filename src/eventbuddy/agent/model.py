"""Chat-model factory for the Phase 1.7 tool-calling agent.

The single place that knows how to point a LangChain `ChatOpenAI` at the GreenNode
MaaS OpenAI-compatible endpoint. The chat path uses `ChatOpenAI` directly (rather than
the `LLMGateway` openai wrapper) because `create_react_agent` needs a LangChain chat
model that supports `bind_tools` → native `tool_calls`. The non-chat LLM uses
(broadcast compose, summaries) keep using `LLMGateway`."""
from collections.abc import Callable

from langchain_openai import ChatOpenAI

from eventbuddy.config import settings


def build_chat_model(*, temperature: float = 0.0, model: str | None = None) -> ChatOpenAI:
    """Construct the chat model bound to MaaS from settings. Does not touch the network."""
    return ChatOpenAI(
        base_url=settings.agentbase_llm_base_url,
        api_key=settings.agentbase_llm_api_key or "unset",
        model=model or settings.llm_chat_model,
        temperature=temperature,
    )


def make_token_counter() -> Callable[[list], int]:
    """A model-agnostic, dependency-free token counter for the working-window trimmer.

    The trimmer (`trim_messages`) defaults to counting via the chat model, but
    langchain-openai routes that through tiktoken keyed on the model NAME and raises
    `NotImplementedError` for vendor-namespaced MaaS models (e.g. 'google/gemma-4-31b-it',
    'qwen/qwen3-5-27b'). We approximate instead (~4 chars/token + small per-message
    overhead): exactness doesn't matter here — we only need to bound the window to ~4096
    tokens while cutting on user/assistant boundaries. Avoids tiktoken's lazy network
    vocab download, so it can't introduce a runtime failure mode inside the container."""

    def count(messages: list) -> int:
        total = 0
        for m in messages:
            content = getattr(m, "content", m)
            if not isinstance(content, str):
                content = str(content)
            total += (len(content) // 4) + 4
        return total

    return count
