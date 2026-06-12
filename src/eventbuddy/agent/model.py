"""Chat-model factory for the Phase 1.7 tool-calling agent.

The single place that knows how to point a LangChain `ChatOpenAI` at the GreenNode
MaaS OpenAI-compatible endpoint. The chat path uses `ChatOpenAI` directly (rather than
the `LLMGateway` openai wrapper) because `create_react_agent` needs a LangChain chat
model that supports `bind_tools` → native `tool_calls`. The non-chat LLM uses
(broadcast compose, summaries) keep using `LLMGateway`."""
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
