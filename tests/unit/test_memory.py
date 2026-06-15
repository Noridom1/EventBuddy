import fakeredis
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from eventbuddy.agent import memory as mem
from eventbuddy.agent.memory import build_checkpointer, flush_all_windows, session_lock


def test_build_checkpointer_in_memory_when_no_redis(monkeypatch):
    monkeypatch.setattr(mem.settings, "redis_url", "")
    assert isinstance(build_checkpointer(), InMemorySaver)


def test_build_checkpointer_redis_with_24h_ttl(monkeypatch):
    # RedisSaver connects on construction, so patch it to capture the config (no live Redis).
    captured = {}

    def fake_redis_saver(url, *, ttl):
        captured["url"], captured["ttl"] = url, ttl
        return object()

    monkeypatch.setattr(mem.settings, "redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(mem, "RedisSaver", fake_redis_saver)

    build_checkpointer()

    assert captured["url"] == "redis://localhost:6379/0"
    assert captured["ttl"]["default_ttl"] == 24 * 60
    assert captured["ttl"]["refresh_on_read"] is True


def test_session_lock_yields_and_releases():
    r = fakeredis.FakeStrictRedis(decode_responses=True)
    with session_lock("dm:u1", redis_client=r):
        assert r.get("lock:dm:u1") is not None
    assert r.get("lock:dm:u1") is None  # released on exit


def test_session_lock_does_not_overlap_same_key():
    r = fakeredis.FakeStrictRedis(decode_responses=True)
    with session_lock("event:ch1", redis_client=r):
        with pytest.raises(TimeoutError):
            with session_lock("event:ch1", redis_client=r, timeout=0.15, poll=0.02):
                pass


def test_session_lock_noop_without_redis(monkeypatch):
    monkeypatch.setattr(mem.settings, "redis_url", "")
    with session_lock("dm:u1"):  # no redis_client, no redis_url -> no-op, no raise
        pass


def test_flush_all_windows_clears_in_memory_saver():
    saver = InMemorySaver()
    saver.storage["dm:u1"] = {"x": 1}
    saver.storage["dm:u2"] = {"y": 2}
    n = flush_all_windows(saver)
    assert n == 2
    assert saver.storage == {}


def test_flush_all_windows_scan_deletes_checkpoint_keys(monkeypatch):
    r = fakeredis.FakeStrictRedis(decode_responses=True)
    # langgraph checkpoint keys for two threads, plus an unrelated app key that must survive.
    r.set("checkpoint:dm:u1:ns:c1", "1")
    r.set("checkpoint:event:ch9:ns:c2", "1")
    r.set("checkpoint_write:dm:u1:ns:c1:0", "1")
    r.set("session:u1", "{}")  # not a checkpoint key — left intact
    monkeypatch.setattr(mem.settings, "redis_url", "redis://x")
    monkeypatch.setattr("eventbuddy.data.redis.get_redis", lambda: r)

    n = flush_all_windows(object())  # non-InMemorySaver -> Redis path
    assert n == 3
    assert r.get("session:u1") == "{}"
    assert not list(r.scan_iter(match="checkpoint*"))


def test_flush_all_windows_noop_without_redis(monkeypatch):
    monkeypatch.setattr(mem.settings, "redis_url", "")
    assert flush_all_windows(object()) == 0
