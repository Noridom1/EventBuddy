"""Impl 4 — RosterStore: a transient, TTL'd Redis stash for a read roster (mirrors the
pending store, but `get` is repeatable — the EO may send after a back-and-forth)."""
from eventbuddy.agent.roster_store import RosterStore


class _FakeRedis:
    def __init__(self):
        self.store, self.ex = {}, {}

    def set(self, k, v, ex=None):
        self.store[k], self.ex[k] = v, ex

    def get(self, k):
        return self.store.get(k)


def test_put_returns_token_and_get_round_trips():
    store = RosterStore(_FakeRedis(), ttl=99)
    reading = {"emails": ["a@x.com"], "rows": [{"email": "a@x.com"}]}
    token = store.put(reading)
    assert token
    assert store.get(token) == reading


def test_get_is_repeatable_not_one_shot():
    store = RosterStore(_FakeRedis())
    token = store.put({"emails": []})
    assert store.get(token) is not None
    assert store.get(token) is not None  # unlike the pending store, not consumed


def test_ttl_is_applied():
    r = _FakeRedis()
    RosterStore(r, ttl=1234).put({"emails": []})
    assert list(r.ex.values())[0] == 1234


def test_get_missing_returns_none():
    assert RosterStore(_FakeRedis()).get("nope") is None
