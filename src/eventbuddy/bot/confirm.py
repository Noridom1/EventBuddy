"""HITL confirm handler (Implementation 1, action plane).

An Adaptive Card `Action.Submit` arrives as a *new* message activity carrying `activity.value`
(the card's `data` dict). The activity router intercepts those before the agent and routes
here. This handler owns the **authorization decision** (cross-cutting rule 2: never trust the
card); the actual Microsoft Graph sends + `audit_log` writes live in an injected `execute_fn`
closure (the composition-root pattern — see `wiring.py`), keeping this layer thin and unit
-testable without Bot Framework or Graph.

Authorization (defense in depth, §11): the clicker must be the *same user* who prepared the
action (`requested_by`, already moderator-gated at prepare time) **and** still pass a role
check. The pending payload is one-shot (`pop`), so a replayed click sees nothing."""
from eventbuddy.bot.auth import ROLE_RANK
from eventbuddy.common.logging import get_logger

log = get_logger("bot.confirm")

_EXPIRED = "That action expired or was already handled — please ask me to prepare it again."
_DENIED = "You're not allowed to confirm this action."


class ConfirmHandler:
    def __init__(self, *, pending_store, role_resolver, execute_fn, min_role: str = "moderator"):
        self._pending = pending_store
        self._role_resolver = role_resolver
        self._execute = execute_fn
        self._min_role = min_role

    def resolve(self, *, action: str | None, pending_id: str | None, channel: str | None,
                clicker: str, scope: str = "personal", channel_id: str | None = None) -> str:
        """Pure decision + dispatch; returns the reply text. Separated from `handle` so it can
        be tested without a TurnContext."""
        if not pending_id:
            return _EXPIRED
        try:
            payload = self._pending.pop(pending_id)
        except Exception as e:  # noqa: BLE001 — Redis down: degrade, don't 500
            log.warning(f"pending store unavailable ({type(e).__name__}: {e})")
            return _EXPIRED
        if payload is None:
            return _EXPIRED

        event_id = payload.get("event_id")
        role = self._role_resolver(
            user_id=clicker, scope=scope, channel_id=channel_id, event_id=event_id
        )
        # Generic event-less sends (send_email / send_teams_message) carry their own role floor
        # ("member") so any member can confirm their own draft; event actions omit it and keep
        # the handler's default moderator gate. The drafter==clicker check always applies.
        min_role = payload.get("min_role", self._min_role)
        authorized = (
            clicker == payload.get("requested_by")
            and ROLE_RANK.get(role, 0) >= ROLE_RANK.get(min_role, ROLE_RANK[self._min_role])
        )

        ok, summary = self._execute(
            payload=payload, channel=channel, actor=clicker, authorized=authorized
        )
        if not authorized:
            return _DENIED
        return summary

    async def handle(self, turn_context) -> None:
        activity = turn_context.activity
        value = activity.value if isinstance(activity.value, dict) else {}
        clicker = activity.from_property.id if activity.from_property else "unknown"
        conv = activity.conversation
        scope = "channel" if (conv and getattr(conv, "is_group", False)) else "personal"
        # Plan 13 — acquire the clicker's delegated Graph token so the confirmed send acts on
        # their behalf, and publish it to the request-scoped ContextVar that `graph_for()`
        # reads inside `execute_fn`. None when not signed in / app-only configured — the
        # execute path then degrades (sign-in prompt) or uses the app-only fallback.
        from eventbuddy.integrations.graph.delegated import (
            acquire_graph_token,
            reset_graph_token,
            set_graph_token,
        )
        graph_token = await acquire_graph_token(turn_context)
        token_handle = set_graph_token(graph_token)
        try:
            reply = self.resolve(
                action=value.get("action"),
                pending_id=value.get("pending_id"),
                channel=value.get("channel"),
                clicker=clicker,
                scope=scope,
                channel_id=conv.id if conv else None,
            )
        finally:
            reset_graph_token(token_handle)
        await turn_context.send_activity(reply)
