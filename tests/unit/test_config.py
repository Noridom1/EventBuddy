# tests/unit/test_config.py
from eventbuddy.config import Settings


def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("AGENTBASE_LLM_BASE_URL", "https://maas.example/v1")
    monkeypatch.setenv("AGENTBASE_LLM_API_KEY", "k")
    s = Settings()
    assert s.database_url == "postgresql+psycopg://u:p@localhost/db"
    assert s.llm_chat_model  # has a default
    assert s.port == 8080  # AgentBase contract default
