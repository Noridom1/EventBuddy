from langchain_core.messages import AIMessage, HumanMessage, trim_messages
from langchain_openai import ChatOpenAI

from eventbuddy.agent import model as model_mod
from eventbuddy.agent.model import build_chat_model, make_token_counter


def test_build_chat_model_uses_settings(monkeypatch):
    monkeypatch.setattr(model_mod.settings, "agentbase_llm_base_url", "https://maas.example/v1")
    monkeypatch.setattr(model_mod.settings, "agentbase_llm_api_key", "sk-test")
    monkeypatch.setattr(model_mod.settings, "llm_chat_model", "qwen/qwen3-5-27b")

    m = build_chat_model()

    assert isinstance(m, ChatOpenAI)
    assert m.model_name == "qwen/qwen3-5-27b"
    assert str(m.openai_api_base) == "https://maas.example/v1"
    assert m.temperature == 0.0


def test_build_chat_model_explicit_model_override(monkeypatch):
    monkeypatch.setattr(model_mod.settings, "agentbase_llm_base_url", "https://maas.example/v1")
    monkeypatch.setattr(model_mod.settings, "agentbase_llm_api_key", "sk-test")

    m = build_chat_model(model="minimax/minimax-m2.5", temperature=0.3)

    assert m.model_name == "minimax/minimax-m2.5"
    assert m.temperature == 0.3


def test_token_counter_is_model_agnostic_and_positive():
    count = make_token_counter()
    msgs = [HumanMessage(content="hello there"), AIMessage(content="general kenobi")]
    n = count(msgs)
    # Approximate (~4 chars/token + per-message overhead) but must be a positive int and
    # grow with content — the trimmer only needs a bounded, monotonic estimate.
    assert isinstance(n, int)
    assert n > 0
    assert count([HumanMessage(content="x" * 400)]) > count([HumanMessage(content="x")])


def test_token_counter_works_with_trim_messages_for_any_model_name():
    # Regression: the default (count via the model) raised NotImplementedError for
    # vendor-namespaced MaaS model ids; an explicit counter must let trim_messages run.
    count = make_token_counter()
    msgs = [HumanMessage(content="a" * 100), AIMessage(content="b" * 100),
            HumanMessage(content="keep me")]
    trimmed = trim_messages(
        msgs, max_tokens=20, token_counter=count, strategy="last",
        start_on="human", include_system=False, allow_partial=False,
    )
    assert trimmed and trimmed[-1].content == "keep me"
