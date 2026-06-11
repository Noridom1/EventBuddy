from types import SimpleNamespace

from botbuilder.integration.aiohttp import (
    CloudAdapter,
    ConfigurationBotFrameworkAuthentication,
)

from eventbuddy.config import settings


def build_adapter() -> CloudAdapter:
    # CloudAdapter + ConfigurationBotFrameworkAuthentication live in
    # botbuilder.integration.aiohttp (botbuilder 4.17), not botbuilder.core.
    # Both read APP_ID/APP_PASSWORD attributes off a configuration object; the
    # auth builds the credential factory internally. With empty creds (Phase 0)
    # APP_TYPE defaults to MultiTenant, i.e. an auth-disabled adapter.
    configuration = SimpleNamespace(
        APP_ID=settings.microsoft_app_id,
        APP_PASSWORD=settings.microsoft_app_password,
    )
    auth = ConfigurationBotFrameworkAuthentication(configuration)
    return CloudAdapter(auth)
