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
    # Vision model for reading images / image-only PDFs (Impl 5). A SEPARATE model from the
    # text chat brain — the agent's reasoning loop stays text-only; `read_event_file` makes an
    # isolated multimodal call here and hands the resulting text back. `google/gemma-4-31b-it`
    # is verified on the MaaS endpoint (accepts OpenAI image_url content; scripts/probe_vision.py,
    # 2026-06-14). Empty model or LLM_VISION_ENABLED=false → image reading degrades cleanly while
    # text files still read.
    llm_vision_model: str = "google/gemma-4-31b-it"
    llm_vision_enabled: bool = True

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
    # The Teams team/group id to create event channels under, and the fallback for channel
    # Graph calls before an event's real `teams_team_id` is observed (Impl 3). Distinct from
    # the tenant id; empty → fall back to the tenant id for back-compat (single-team demo).
    microsoft_team_id: str = ""

    # Microsoft Graph (client-credentials baseline; AgentBase Identity later)
    graph_tenant_id: str = ""
    graph_client_id: str = ""
    graph_client_secret: str = ""
    # Sender mailbox for outbound mail. With *application* Graph permissions there is no "me",
    # so `send_mail` posts as /users/{graph_sender_upn}/sendMail. This is the mailbox an
    # Application Access Policy should scope Mail.Send to (UPN or email, e.g. eventbuddy@corp).
    # Empty → the mail capability raises a clear "sender not configured" error (degrades visibly).
    graph_sender_upn: str = ""

    log_level: str = "INFO"

    # HITL action plane (Impl 1). TTL (seconds) of a prepared pending action in Redis: long
    # enough for the user to confirm the Adaptive Card, short enough to bound replay.
    pending_action_ttl: int = 60 * 60

    # Feedback / report plane (Impl 2). FEEDBACK_FORM_URL is the templated *send* link the
    # post-event jobs mail out ({event_id} is interpolated). FEEDBACK_WORKBOOK_URL is the
    # SharePoint share link to the Form's *responses* Excel workbook — the chosen fetch path
    # (MS Forms has no supported response API). Empty → that path degrades to "not configured".
    feedback_form_url: str = ""
    feedback_workbook_url: str = ""

    # Agentic web tools (Impl 3). Tavily powers both `web_search` (ranked snippets) and
    # `web_fetch` (clean page extraction). Empty key → the web tools are not registered, so
    # the agent simply doesn't advertise a capability it can't fulfil (graceful degradation).
    tavily_api_key: str = ""
    web_search_max_results: int = 5
    web_search_timeout: int = 15

    # Dev-only debug HTTP routes (no Bot Framework auth) — keep off in production.
    dev_routes_enabled: bool = False


settings = Settings()
