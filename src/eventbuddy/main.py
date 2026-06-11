from fastapi import FastAPI

from eventbuddy.api import health
from eventbuddy.common.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="EventBuddy")
    app.include_router(health.router)
    return app


app = create_app()
