import msal

from eventbuddy.config import settings


class GraphTokenProvider:
    """Interface: return a valid Graph bearer token."""

    def get_token(self) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class MsalTokenProvider(GraphTokenProvider):
    """Client-credentials flow. Swap for AgentBaseIdentityTokenProvider later (architecture §10)."""

    def __init__(self):
        self._app = msal.ConfidentialClientApplication(
            client_id=settings.graph_client_id,
            client_credential=settings.graph_client_secret,
            authority=f"https://login.microsoftonline.com/{settings.graph_tenant_id}",
        )

    def get_token(self) -> str:
        result = self._app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" not in result:
            raise RuntimeError(f"Graph token error: {result.get('error_description')}")
        return result["access_token"]
