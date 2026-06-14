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
        from eventbuddy.agent.wiring import build_summarizer
        summarizer = build_summarizer()
        if summarizer is not None:
            schedule_summarizer(scheduler, summarizer)
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
