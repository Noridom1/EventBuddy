from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # AgentBase runtime contract
    port: int = 8080

    # Data
    database_url: str = "postgresql+psycopg://eventbuddy:eventbuddy@localhost:5432/eventbuddy"
    redis_url: str = "redis://localhost:6379/0"

    # LLM (GreenNode MaaS, OpenAI-compatible)
    agentbase_llm_base_url: str = ""
    agentbase_llm_api_key: str = ""
    llm_chat_model: str = "gemma-4-31b-it"
    llm_summary_model: str = "qwen-3-27b"

    # Microsoft Bot Framework
    microsoft_app_id: str = ""
    microsoft_app_password: str = ""
    microsoft_app_tenant_id: str = ""

    # Microsoft Graph (client-credentials baseline; AgentBase Identity later)
    graph_tenant_id: str = ""
    graph_client_id: str = ""
    graph_client_secret: str = ""

    log_level: str = "INFO"

    # Dev-only debug HTTP routes (no Bot Framework auth) — keep off in production.
    dev_routes_enabled: bool = False


settings = Settings()
