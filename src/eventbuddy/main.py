from contextlib import asynccontextmanager

from fastapi import FastAPI

from eventbuddy.api import health, messages, webhooks
from eventbuddy.common.logging import configure_logging, get_logger
from eventbuddy.config import settings
from eventbuddy.scheduler.triggers import (
    schedule_summarizer,
    shutdown_scheduler,
    start_scheduler,
)

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = start_scheduler()
    try:
        # Schedule only when MaaS creds are present; the job itself rebuilds the summarizer
        # at fire time (no live object captured — the persistent jobstore pickles job args).
        if settings.agentbase_llm_base_url:
            schedule_summarizer(scheduler)
    except Exception as e:  # noqa: BLE001
        log.warning(f"summarizer job not scheduled: {type(e).__name__}: {e}")
    try:
        yield
    finally:
        shutdown_scheduler(scheduler)


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="EventBuddy", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(messages.router)
    app.include_router(webhooks.router)
    from eventbuddy.api import forms
    app.include_router(forms.router)
    if settings.dev_routes_enabled:
        from eventbuddy.api import dev
        app.include_router(dev.router)
    return app


app = create_app()
