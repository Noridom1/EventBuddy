from eventbuddy.agent.session import SessionStore


class _FakeRedis:
    def __init__(self):
        self.kv = {}

    def get(self, k):
        return self.kv.get(k)

    def set(self, k, v, ex=None):
        self.kv[k] = v

    def delete(self, k):
        self.kv.pop(k, None)


def test_set_and_get_current_event():
    store = SessionStore(_FakeRedis())
    assert store.get_current_event("u1") is None
    store.set_current_event("u1", "ev-42")
    assert store.get_current_event("u1") == "ev-42"


def test_clear_current_event():
    store = SessionStore(_FakeRedis())
    store.set_current_event("u1", "ev-42")
    store.clear_current_event("u1")
    assert store.get_current_event("u1") is None
