"""Transient server-side store for a read participant roster (Impl 4).

A roster a tool reads from an uploaded/linked file is stashed here under an opaque token, so
the send tool can resolve the (potentially hundreds of) addresses **server-side** — they never
transit the model's tool-call args or context window (cross-cutting rule 2 + window discipline,
mirroring `PendingActionStore`). TTL'd and **never the DB**: Impl 4 is stateless, so the roster
just expires after the read→confirm→send loop. Redis-backed; the caller catches a Redis outage
and degrades (same contract as the pending store)."""
import json

from eventbuddy.common.ids import new_id

ROSTER_KEY = "roster_reading:{token}"
DEFAULT_TTL = 60 * 60  # 1h — long enough for the EO to confirm, short enough to expire


class RosterStore:
    def __init__(self, redis_client, ttl: int = DEFAULT_TTL):
        self.r = redis_client
        self.ttl = ttl

    def _key(self, token: str) -> str:
        return ROSTER_KEY.format(token=token)

    def put(self, reading: dict) -> str:
        """Store a roster reading; returns a fresh opaque token to hand the model."""
        token = new_id()
        self.r.set(self._key(token), json.dumps(reading), ex=self.ttl)
        return token

    def get(self, token: str) -> dict | None:
        raw = self.r.get(self._key(token))
        return json.loads(raw) if raw else None
