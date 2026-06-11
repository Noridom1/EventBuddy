from botbuilder.core import CloudAdapter, ConfigurationBotFrameworkAuthentication
from botbuilder.core.integration import ConfigurationServiceClientCredentialFactory

from eventbuddy.config import settings


def build_adapter() -> CloudAdapter:
    # NOTE (verify against installed SDK): CloudAdapter + ConfigurationBotFrameworkAuthentication
    # is the botbuilder 4.16 path.
    auth = ConfigurationBotFrameworkAuthentication(
        {},
        credentials_factory=ConfigurationServiceClientCredentialFactory(
            app_id=settings.microsoft_app_id,
            app_password=settings.microsoft_app_password,
        ),
    )
    return CloudAdapter(auth)
