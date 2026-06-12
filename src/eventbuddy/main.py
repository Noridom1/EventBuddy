from contextlib import asynccontextmanager

from fastapi import FastAPI

from eventbuddy.api import health, messages, webhooks
from eventbuddy.common.logging import configure_logging
from eventbuddy.config import settings
from eventbuddy.scheduler.triggers import shutdown_scheduler, start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = start_scheduler()
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
    if settings.dev_routes_enabled:
        from eventbuddy.api import dev
        app.include_router(dev.router)
    return app


app = create_app()
