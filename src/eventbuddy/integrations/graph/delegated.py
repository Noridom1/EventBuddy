"""Delegated (on-behalf-of the signed-in user) Graph auth.

IT (Entra admin) rejected all **application** Graph permissions — the bot may only act with
**delegated** permissions, bounded by what the interacting user can already access (see
`__plans__/13-delegated-graph-auth-migration.md`). This module holds the delegated half of
the auth seam; the legacy app-only `MsalTokenProvider` (in `token.py`) stays as the
graceful-degradation fallback when no OAuth connection is configured.

**How the token is obtained.** We rely on an **OAuth Connection** configured on the Azure Bot
(Teams SSO). The Bot Framework *token service* performs the SSO→on-behalf-of exchange and
**stores the refresh token for us** — so EventBuddy never persists raw refresh tokens and needs
no encryption-at-rest key. On a turn, the bot asks the token service for the caller's Graph
token; for a background job it asks the token service for the host's previously-stored token.

**How the token reaches a GraphClient.** A request-scoped `ContextVar` carries the bearer
string, mirroring the `ToolTrace` ContextVar idiom in `agent/tools.py`. The runner (interactive
turns), the confirm handler (HITL card clicks), and the scheduler (background jobs) each set it
around their unit of work; `wiring.graph_for()` reads it and wraps it in a `StaticTokenProvider`.
This avoids threading a token argument through every capability closure.

Everything here is **best-effort and degrades**: no connection configured / no cached token /
expired token → the helpers return ``None`` and callers fall back (app-only) or surface a clean
"please sign in" message. They never raise into a turn."""
from contextlib import contextmanager
from contextvars import ContextVar

from eventbuddy.common.logging import get_logger
from eventbuddy.config import settings

log = get_logger("integrations.graph.delegated")

GRAPH_SCOPES = ["https://graph.microsoft.com/.default"]

# Request-scoped delegated Graph bearer token. Set by the runner / confirm handler / scheduler
# around their work; read by `wiring.graph_for()`. Default None → no delegated token in scope.
_current_graph_token: ContextVar[str | None] = ContextVar(
    "eventbuddy_graph_token", default=None
)

# Request-scoped "a Graph op was attempted this turn but no user token was in scope" flag. Set
# by `graph_for()` when delegated auth is on and the caller isn't signed in; the activity router
# clears it before each turn and checks it after, to auto-prompt sign-in only when Graph was
# actually needed (never on plain chit-chat).
_signin_needed: ContextVar[bool] = ContextVar("eventbuddy_signin_needed", default=False)


def mark_signin_needed() -> None:
    """Record that a Graph operation this turn lacked a delegated user token."""
    _signin_needed.set(True)


def signin_needed() -> bool:
    """True if a Graph op this turn needed a user token we didn't have (→ prompt sign-in)."""
    return _signin_needed.get()


def clear_signin_needed() -> None:
    """Reset the per-turn sign-in-needed flag (the router calls this before running a turn)."""
    _signin_needed.set(False)


def delegated_enabled() -> bool:
    """True when delegated auth is configured (an Azure Bot OAuth connection name is set).
    When False, the system keeps using the legacy app-only `MsalTokenProvider` — preserving
    the graceful-degradation invariant during the migration."""
    return bool(settings.graph_oauth_connection_name)


class StaticTokenProvider:
    """A `token_provider` (the `GraphClient` contract: a `.get_token()` returning a bearer
    string) wrapping a token already acquired upstream from the Bot Framework token service.
    Delegated tokens are short-lived and acquired per request, so there's nothing to refresh
    here — the token service owns refresh."""

    def __init__(self, token: str):
        self._token = token

    def get_token(self) -> str:
        if not self._token:
            raise RuntimeError("StaticTokenProvider: no delegated Graph token available")
        return self._token


def current_graph_token() -> str | None:
    """The delegated Graph token for the current request/job, or None when none is in scope."""
    return _current_graph_token.get()


def set_graph_token(token: str | None) -> object:
    """Set the request-scoped delegated token; returns the reset token (pair with `reset`)."""
    return _current_graph_token.set(token)


def reset_graph_token(reset_token: object) -> None:
    _current_graph_token.reset(reset_token)


@contextmanager
def use_graph_token(token: str | None):
    """Scope a delegated Graph token to a block (background jobs / confirm handling). The
    runner uses the explicit set/reset pair instead, to fit its existing try/finally."""
    handle = set_graph_token(token)
    try:
        yield
    finally:
        reset_graph_token(handle)


def token_scopes(token: str | None) -> str | None:
    """Best-effort diagnostic: decode the (UNVERIFIED) JWT payload of a delegated Graph token and
    return its `scp` claim — the space-delimited delegated scopes the token was actually granted.
    Returns None when there's no token or it can't be parsed. Used only to explain a 403 in the
    logs without needing Azure-admin access to inspect the OAuth connection. Scope *names* aren't
    sensitive and we never log the token itself; we don't verify the signature (we're reading our
    own token's claims, not trusting them). Never raises."""
    if not token:
        return None
    try:
        import base64
        import json

        payload_b64 = token.split(".")[1]
        padding = "=" * (-len(payload_b64) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
        return claims.get("scp")
    except Exception:  # noqa: BLE001 — diagnostic only; a malformed token just yields None
        return None


def _user_token_client(turn_context):
    """The `CloudAdapter` surfaces the token service as a `UserTokenClient` stored in turn_state
    under ``CloudAdapterBase.USER_TOKEN_CLIENT_KEY`` (the literal "UserTokenClient"). NOTE: the
    class lives in `botframework.connector.auth`, not `botbuilder.core` — importing it from the
    latter (as we once did) raises ImportError and silently nulls this whole path. We key off the
    string directly to avoid that. Returns the client, or None when it isn't present."""
    try:
        return turn_context.turn_state.get("UserTokenClient")
    except Exception:  # noqa: BLE001 — no turn_state / older SDK
        return None


async def acquire_graph_token(turn_context, magic_code: str | None = None) -> str | None:
    """Interactive path: ask the Bot Framework token service for the caller's Graph token on the
    configured OAuth connection. Returns the bearer string, or None when the user hasn't signed
    in yet (the caller then prompts sign-in). `magic_code` completes a just-finished sign-in.
    Never raises.

    Tries the CloudAdapter `UserTokenClient` first, then the legacy `adapter.get_user_token` —
    the exact surface is SDK-version-specific and validated in-tenant. A missing token is a
    normal 'not signed in yet' result, not an error."""
    if not delegated_enabled():
        return None
    connection = settings.graph_oauth_connection_name
    activity = turn_context.activity
    user_id = activity.from_property.id if activity.from_property else None
    channel_id = getattr(activity, "channel_id", None)

    client = _user_token_client(turn_context)
    if client is not None:
        try:
            res = await client.get_user_token(user_id, connection, channel_id, magic_code)
            token = getattr(res, "token", None) if res else None
            if token:
                return token
        except Exception as e:  # noqa: BLE001 — try the adapter path next
            # WARNING (not debug): during sign-in triage this is the real reason a verifyState
            # completion returned no token (e.g. an AADSTS code, correlation miss). Surfaces at
            # the default INFO level without turning on global DEBUG.
            log.warning(f"UserTokenClient token fetch failed ({type(e).__name__}: {e})")

    # Legacy adapter fallback only — CloudAdapter has no get_user_token (the UserTokenClient
    # above is the route). Guard so we never AttributeError on the modern adapter.
    adapter = getattr(turn_context, "adapter", None)
    if adapter is None or not hasattr(adapter, "get_user_token"):
        return None
    try:
        res = await adapter.get_user_token(turn_context, connection, magic_code)
        token = getattr(res, "token", None) if res else None
        return token or None
    except Exception as e:  # noqa: BLE001 — degrade: treat as "no token", never break the turn
        log.warning(f"adapter token fetch failed ({type(e).__name__}: {e})")
        return None


async def _sign_in_link(turn_context, connection: str) -> str | None:
    """Resolve the OAuth sign-in URL for the connection (UserTokenClient → adapter fallback)."""
    client = _user_token_client(turn_context)
    if client is not None:
        try:
            resource = await client.get_sign_in_resource(
                connection, turn_context.activity, None)
            link = getattr(resource, "sign_in_link", None)
            if link:
                return link
            log.warning(
                f"UserTokenClient returned no sign_in_link for connection '{connection}' "
                "— is the OAuth connection configured on the Azure Bot resource?"
            )
        except Exception as e:  # noqa: BLE001
            log.warning(
                f"UserTokenClient sign-in resource failed for connection '{connection}' "
                f"({type(e).__name__}: {e})"
            )
    else:
        log.warning("no UserTokenClient in turn_state — cannot resolve an OAuth sign-in link")
    # Legacy BotFrameworkAdapter exposed get_sign_in_resource directly; CloudAdapter does not.
    # Only try it when present, so we never AttributeError on the modern adapter.
    adapter = getattr(turn_context, "adapter", None)
    if adapter is None or not hasattr(adapter, "get_sign_in_resource"):
        return None
    try:
        resource = await adapter.get_sign_in_resource(turn_context, connection)
        link = getattr(resource, "sign_in_link", None)
        if not link:
            log.warning(
                f"adapter returned no sign_in_link for connection '{connection}' "
                "— is the OAuth connection configured on the Azure Bot resource?"
            )
        return link
    except Exception as e:  # noqa: BLE001
        log.warning(
            f"adapter sign-in resource failed for connection '{connection}' "
            f"({type(e).__name__}: {e})"
        )
        return None


async def send_signin_prompt(turn_context, text: str | None = None) -> bool:
    """Send a Teams OAuth sign-in card for the configured connection, so the user can consent
    once and let the token service refresh thereafter. Best-effort: returns False (and the
    caller proceeds degraded) if the connection isn't available. Never raises into the turn."""
    if not delegated_enabled():
        return False
    connection = settings.graph_oauth_connection_name
    try:
        from botbuilder.core import CardFactory, MessageFactory
        from botbuilder.schema import ActionTypes, CardAction, OAuthCard

        sign_in_link = await _sign_in_link(turn_context, connection)
        if sign_in_link:
            log.info(f"sending OAuth card for connection '{connection}' (sign-in link resolved)")
        else:
            log.warning(
                f"sending OAuth card for connection '{connection}' with NO sign-in link — "
                "the button will fail in Teams ('Something went wrong'); the OAuth connection "
                "is likely missing/misconfigured on the Azure Bot resource"
            )
        card = OAuthCard(
            text=text or "Please sign in so I can act on your behalf in Microsoft 365.",
            connection_name=connection,
            buttons=[CardAction(type=ActionTypes.signin, title="Sign in", value=sign_in_link)],
        )
        await turn_context.send_activity(
            MessageFactory.attachment(CardFactory.oauth_card(card))
        )
        return True
    except Exception as e:  # noqa: BLE001 — degrade silently rather than break the turn
        log.warning(f"sign-in prompt failed ({type(e).__name__}: {e})")
        return False


async def sign_out_user(turn_context) -> bool:
    """Clear the caller's cached token for the configured OAuth connection in the Bot Framework
    token store. Needed when the consented scope set changed (e.g. IT granted a new delegated
    permission): the token service caches the original refresh token, so a stale grant keeps
    handing back tokens with the old `scp` until the user signs out and signs in again. Returns
    True when a sign-out call was issued. Best-effort and never raises into the turn — mirrors
    the UserTokenClient → legacy-adapter fallback used by `acquire_graph_token`."""
    if not delegated_enabled():
        return False
    connection = settings.graph_oauth_connection_name
    activity = turn_context.activity
    user_id = activity.from_property.id if activity.from_property else None
    channel_id = getattr(activity, "channel_id", None)

    client = _user_token_client(turn_context)
    if client is not None:
        try:
            await client.sign_out_user(user_id, connection, channel_id)
            return True
        except Exception as e:  # noqa: BLE001 — try the adapter path next
            log.debug(f"UserTokenClient sign-out failed ({type(e).__name__}: {e})")

    # Legacy BotFrameworkAdapter exposed sign_out_user(turn_context, connection, user_id);
    # CloudAdapter routes through the UserTokenClient above. Guard so we never AttributeError.
    adapter = getattr(turn_context, "adapter", None)
    if adapter is None or not hasattr(adapter, "sign_out_user"):
        return False
    try:
        await adapter.sign_out_user(turn_context, connection, user_id)
        return True
    except Exception as e:  # noqa: BLE001 — degrade: never break the turn
        log.warning(f"adapter sign-out failed ({type(e).__name__}: {e})")
        return False


def acquire_graph_token_for_user(user_id: str, channel_id: str | None = None) -> str | None:
    """Background path (synchronous — APScheduler jobs are sync): ask the token service for a
    *previously-consented* user's Graph token, with no active turn. Used by scheduled reminder/
    feedback jobs to act as the host who set them up. Returns None when the host never signed in
    or the stored token expired/was revoked (the job then degrades + the host must
    re-authenticate) — never raises.

    NOTE: retrieving a user token without a TurnContext requires the Bot Framework
    `UserTokenClient` constructed with the bot's app credentials; the exact call is
    SDK-version-specific and must be validated against the live Azure Bot once the OAuth
    connection exists. Until then this returns None and the background path stays best-effort,
    exactly as it was under app-only auth (it degraded to 'failed' without creds)."""
    if not delegated_enabled():
        return None
    try:
        from botframework.connector.auth import MicrosoftAppCredentials
        from botframework.connector.token_api import TokenApiClient

        creds = MicrosoftAppCredentials(
            settings.microsoft_app_id, settings.microsoft_app_password
        )
        client = TokenApiClient(creds)
        token_response = client.user_token.get_token(
            user_id=user_id,
            connection_name=settings.graph_oauth_connection_name,
            channel_id=channel_id,
        )
        token = getattr(token_response, "token", None) if token_response else None
        return token or None
    except Exception as e:  # noqa: BLE001 — no token / SDK mismatch → degrade
        log.warning(f"background delegated token fetch failed ({type(e).__name__}: {e})")
        return None
