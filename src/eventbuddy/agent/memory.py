"""Working-window memory: the LangGraph checkpointer (Redis) + a per-thread lock.

The working window is the live message graph, keyed by the scope-aware `thread_id`
(`event:{channel_id}` | `dm:{user_id}`), persisted in the existing Redis with a 24h TTL.
A per-thread lock serializes concurrent runs on a shared event thread so simultaneous
posts don't clobber the checkpoint. Without a configured Redis, both degrade to in-memory
/ no-op so unit and dev runs still work."""
import time
import uuid
from contextlib import contextmanager

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.redis import RedisSaver

from eventbuddy.config import settings

WINDOW_TTL_MINUTES = 24 * 60  # 24h working-window TTL
LOCK_KEY = "lock:{thread_id}"
# Key prefixes the langgraph Redis checkpointer writes under (langgraph.checkpoint.redis.base:
# CHECKPOINT_PREFIX / CHECKPOINT_WRITE_PREFIX). A full reset scan-deletes these — it empties the
# working windows for every thread while leaving the RediSearch indices and other app keys intact.
CHECKPOINT_KEY_PATTERNS = ("checkpoint:*", "checkpoint_write:*")


def build_checkpointer():
    """Return the conversation checkpointer. RedisSaver (24h TTL) when `redis_url` is set,
    else an InMemorySaver so dev/unit runs work without Redis. Call `setup_checkpointer`
    once at startup to create the Redis search indices (best-effort)."""
    if not settings.redis_url:
        return InMemorySaver()
    return RedisSaver(
        settings.redis_url,
        ttl={"default_ttl": WINDOW_TTL_MINUTES, "refresh_on_read": True},
    )


def setup_checkpointer(checkpointer) -> bool:
    """Best-effort index creation for a RedisSaver. No-op for InMemorySaver / on failure
    (the chat path degrades to the regex router rather than crashing)."""
    setup = getattr(checkpointer, "setup", None)
    if setup is None:
        return False
    try:
        setup()
        return True
    except Exception:
        return False


def flush_all_windows(checkpointer) -> int:
    """Delete EVERY thread's working window (dev/demo reset — wipes all users, not one thread).
    Returns the number of entries cleared. Handles both the in-memory saver (clear its stores)
    and the Redis saver (scan-delete the checkpoint key space). Best-effort: any Redis hiccup
    leaves the rest of the reset to proceed."""
    if isinstance(checkpointer, InMemorySaver):
        n = len(getattr(checkpointer, "storage", {}) or {})
        for attr in ("storage", "writes", "blobs"):
            d = getattr(checkpointer, attr, None)
            if isinstance(d, dict):
                d.clear()
        return n
    if not settings.redis_url:
        return 0
    from eventbuddy.data.redis import get_redis

    client = get_redis()
    deleted = 0
    try:
        for pattern in CHECKPOINT_KEY_PATTERNS:
            for key in client.scan_iter(match=pattern, count=500):
                deleted += client.delete(key)
    except Exception:  # noqa: BLE001 — dev/demo convenience, never raise mid-reset
        pass
    return deleted


@contextmanager
def session_lock(thread_id, *, redis_client=None, ttl=30, timeout=10.0, poll=0.05):
    """Acquire a per-thread lock so concurrent posts to a shared `event:` thread serialize.
    No-op when no Redis is configured. Raises TimeoutError if the lock can't be acquired."""
    if redis_client is None and not settings.redis_url:
        yield
        return
    if redis_client is None:
        from eventbuddy.data.redis import get_redis

        redis_client = get_redis()

    key = LOCK_KEY.format(thread_id=thread_id)
    token = uuid.uuid4().hex
    deadline = time.monotonic() + timeout
    while not redis_client.set(key, token, nx=True, ex=ttl):
        if time.monotonic() >= deadline:
            raise TimeoutError(f"could not acquire {key} within {timeout}s")
        time.sleep(poll)
    try:
        yield
    finally:
        if redis_client.get(key) == token:
            redis_client.delete(key)
