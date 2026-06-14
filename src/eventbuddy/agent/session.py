import json

SESSION_KEY = "session:{user_id}"
SESSION_TTL = 60 * 60 * 24  # 24h


class SessionStore:
    """Redis-backed per-user session for context switching (architecture §8)."""

    def __init__(self, redis_client):
        self.r = redis_client

    def _key(self, user_id: str) -> str:
        return SESSION_KEY.format(user_id=user_id)

    def _load(self, user_id: str) -> dict:
        raw = self.r.get(self._key(user_id))
        return json.loads(raw) if raw else {}

    def _save(self, user_id: str, data: dict) -> None:
        self.r.set(self._key(user_id), json.dumps(data), ex=SESSION_TTL)

    def get_current_event(self, user_id: str) -> str | None:
        return self._load(user_id).get("current_event_id")

    def set_current_event(self, user_id: str, event_id: str) -> None:
        data = self._load(user_id)
        data["current_event_id"] = event_id
        self._save(user_id, data)

    def clear_current_event(self, user_id: str) -> None:
        data = self._load(user_id)
        data.pop("current_event_id", None)
        self._save(user_id, data)
