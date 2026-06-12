from langchain_openai import ChatOpenAI

from eventbuddy.agent import model as model_mod
from eventbuddy.agent.model import build_chat_model


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
