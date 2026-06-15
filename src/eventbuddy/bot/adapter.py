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
    #
    # When a tenant id IS set, the bot app is registered single-tenant in our
    # directory, so the connector must authenticate against that tenant's
    # authority — not the default MultiTenant (botframework.com) authority, which
    # fails with AADSTS700016 ("application … not found in the directory 'Bot
    # Framework'"). Set APP_TYPE=SingleTenant + APP_TENANTID so outbound replies
    # (and the OAuth/connector auth) hit the right authority. Empty tenant id →
    # leave MultiTenant, preserving the no-creds / multi-tenant degradation.
    configuration = SimpleNamespace(
        APP_ID=settings.microsoft_app_id,
        APP_PASSWORD=settings.microsoft_app_password,
    )
    if settings.microsoft_app_tenant_id:
        configuration.APP_TYPE = "SingleTenant"
        configuration.APP_TENANTID = settings.microsoft_app_tenant_id
    auth = ConfigurationBotFrameworkAuthentication(configuration)
    return CloudAdapter(auth)
