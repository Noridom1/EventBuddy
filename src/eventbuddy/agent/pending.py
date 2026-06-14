"""Server-side store for HITL pending actions (Implementation 1, action plane).

When the agent *proposes* a destructive/bulk action (send reminders, send mail), the full
payload — recipients, event, the user who requested it — is stashed here under an opaque
token. The Adaptive Card the user confirms carries only that token (+ the chosen channel),
never identity or recipients (cross-cutting rule 2: the model/client can't spoof who or
what). On confirm, the server re-derives everything from this store.

`pop` (get + delete) is the replay guard: a token is one-shot, and the TTL bounds exposure.
Redis-backed, sibling to `SessionStore` — degrades by surfacing a friendly message upstream
when Redis is unavailable (the caller catches)."""
import json

from eventbuddy.common.ids import new_id

PENDING_KEY = "pending_action:{pending_id}"
DEFAULT_TTL = 60 * 60  # 1h — long enough to confirm, short enough to bound replay


class PendingActionStore:
    def __init__(self, redis_client, ttl: int = DEFAULT_TTL):
        self.r = redis_client
        self.ttl = ttl

    def _key(self, pending_id: str) -> str:
        return PENDING_KEY.format(pending_id=pending_id)

    def put(self, payload: dict) -> str:
        """Store a pending-action payload; returns a fresh opaque token to put on the card."""
        pending_id = new_id()
        self.r.set(self._key(pending_id), json.dumps(payload), ex=self.ttl)
        return pending_id

    def get(self, pending_id: str) -> dict | None:
        raw = self.r.get(self._key(pending_id))
        return json.loads(raw) if raw else None

    def pop(self, pending_id: str) -> dict | None:
        """One-shot fetch: read and delete atomically-enough for our needs (a stray double
        click resolves to the second call seeing `None`). Used by the confirm handler."""
        payload = self.get(pending_id)
        if payload is not None:
            self.r.delete(self._key(pending_id))
        return payload
