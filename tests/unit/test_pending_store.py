from eventbuddy.agent.pending import PendingActionStore


class _FakeRedis:
    def __init__(self):
        self.store = {}
        self.ex = {}

    def set(self, k, v, ex=None):
        self.store[k] = v
        self.ex[k] = ex

    def get(self, k):
        return self.store.get(k)

    def delete(self, k):
        self.store.pop(k, None)


def test_put_returns_token_and_get_round_trips():
    r = _FakeRedis()
    store = PendingActionStore(r, ttl=123)
    pid = store.put({"type": "remind", "requested_by": "u1"})
    assert pid  # opaque, non-empty
    assert store.get(pid) == {"type": "remind", "requested_by": "u1"}
    # TTL is applied so a forgotten action can't linger forever.
    assert list(r.ex.values())[0] == 123


def test_pop_is_one_shot():
    store = PendingActionStore(_FakeRedis())
    pid = store.put({"type": "mail"})
    assert store.pop(pid) == {"type": "mail"}
    assert store.pop(pid) is None  # replay guard: second pop sees nothing


def test_get_missing_returns_none():
    assert PendingActionStore(_FakeRedis()).get("nope") is None
