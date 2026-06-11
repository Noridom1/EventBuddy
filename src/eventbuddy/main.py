from fastapi import FastAPI

from eventbuddy.api import health, messages, webhooks
from eventbuddy.common.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="EventBuddy")
    app.include_router(health.router)
    app.include_router(messages.router)
    app.include_router(webhooks.router)
    return app


app = create_app()
