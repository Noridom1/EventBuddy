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
    # Model IDs are namespaced on the MaaS endpoint (verified 2026-06-12 — bare
    # "gemma-4-31b-it"/"qwen-3-27b" return 404). qwen3-5-27b returns clean OpenAI
    # tool_calls, so it's the chat brain for the Phase 1.7 tool-calling agent.
    llm_chat_model: str = "qwen/qwen3-5-27b"
    llm_summary_model: str = "qwen/qwen3-5-27b"

    # Phase 1.7 conversational agent. "llm" = LLM tool-calling brain (requires the MaaS
    # creds above); "regex" forces the deterministic Phase 1 router. Without LLM creds the
    # chat path auto-degrades to regex regardless of this flag.
    agent_mode: str = "llm"

    # Phase 1.8 debug surfacing. When True (default this phase), the LLM agent never
    # silently degrades to the regex router on a *runtime* error: instead the reply carries
    # a debug footer listing every tool call this turn (name + params) with the full
    # exception + traceback for any that failed. Set False to restore the silent regex
    # fallback (and drop the footer). The no-creds / agent_mode=regex degradation is decided
    # at wiring time and is unaffected by this flag.
    agent_debug: bool = True

    # Microsoft Bot Framework
    microsoft_app_id: str = ""
    microsoft_app_password: str = ""
    microsoft_app_tenant_id: str = ""

    # Microsoft Graph (client-credentials baseline; AgentBase Identity later)
    graph_tenant_id: str = ""
    graph_client_id: str = ""
    graph_client_secret: str = ""

    log_level: str = "INFO"

    # HITL action plane (Impl 1). TTL (seconds) of a prepared pending action in Redis: long
    # enough for the user to confirm the Adaptive Card, short enough to bound replay.
    pending_action_ttl: int = 60 * 60

    # Dev-only debug HTTP routes (no Bot Framework auth) — keep off in production.
    dev_routes_enabled: bool = False


settings = Settings()
