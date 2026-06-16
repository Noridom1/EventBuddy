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

    # Microsoft Graph. Two auth modes, selected by whether an OAuth connection is configured:
    #   • Delegated (mandated by IT — Plan 13): set GRAPH_OAUTH_CONNECTION_NAME to the Azure
    #     Bot OAuth connection that does Teams SSO → on-behalf-of. The bot then acts as the
    #     signed-in user, bounded by that user's own access. No tenant-wide app credential.
    #   • App-only fallback (legacy / pre-migration): the client-credentials trio below. Used
    #     only when no OAuth connection is set, preserving graceful degradation during rollout.
    # The Azure Bot OAuth connection name (Teams SSO). Non-empty → delegated auth is active and
    # the app-only client-credentials path below is no longer used for interactive turns.
    graph_oauth_connection_name: str = ""
    graph_tenant_id: str = ""
    graph_client_id: str = ""
    graph_client_secret: str = ""
    # Sender mailbox for outbound mail. With *application* Graph permissions there is no "me",
    # so `send_mail` posts as /users/{graph_sender_upn}/sendMail. This is the mailbox an
    # Application Access Policy should scope Mail.Send to (UPN or email, e.g. eventbuddy@corp).
    # Empty → the mail capability raises a clear "sender not configured" error (degrades visibly).
    graph_sender_upn: str = ""
    # Corporate email domain for the generic send tools (`send_email`, `send_teams_message`).
    # The corp identifies employees by the local part of their address (the alias before "@",
    # e.g. phucnlt2@vng.com.vn → "phucnlt2"), so the tools accept a bare alias and expand it to
    # "{alias}@{corp_email_domain}". Empty → aliases without "@" can't be expanded (the email
    # tool then needs full addresses; Teams resolution still tries mailNickname directly).
    corp_email_domain: str = ""

    log_level: str = "INFO"

    # Impl 11 — landing page on the default endpoint. The runtime endpoint root ("/") serves
    # the Event Buddy install page, and "/download/eventbuddy.zip" hands out the Teams package.
    # Paths are resolved relative to the process CWD (the repo root locally, /app in the
    # container — matching how .env and alembic.ini are located). Missing files degrade to a
    # clean 404 at request time; they never break app startup or the /health probe.
    landing_page_dir: str = "landing_page"
    teams_package_path: str = "teams-app/eventbuddy.zip"
    # Fallback for "/download/eventbuddy.zip" when the bundled ZIP isn't present on disk (e.g.
    # the asset wasn't baked into the image): the route redirects here instead of 404ing, so
    # the landing page's Download button keeps working. Empty → fall back to a 404.
    teams_package_fallback_url: str = (
        "https://vngms-my.sharepoint.com/:u:/r/personal/hanntn6_vng_com_vn/"
        "Documents/Claw-a-thon/eventbuddy.zip?csf=1&web=1&e=AAYkDN"
    )

    # Impl 10 — agent reasoning trace. When True, every turn emits an ordered, structured
    # trace to the logs under the `agent.trace` logger at INFO: the prompt sent to the model
    # (system + window), the model's reasoning + tool_calls, and each tool's input/return.
    # Independent of LOG_LEVEL (visible without global DEBUG noise) and of AGENT_DEBUG (the
    # reply footer). OFF by default — when on, the logs carry user content (prompts, file
    # contents, rosters), so don't enable it against a shared/prod log sink without review.
    agent_trace: bool = False

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

    # Plan 14 — the Teams "EventBuddy is typing…" indicator. On by default; set false to disable
    # it entirely (e.g. while debugging a connector/typing issue). Best-effort decoration, so
    # turning it off never changes a turn's reply.
    typing_indicator_enabled: bool = True


settings = Settings()
