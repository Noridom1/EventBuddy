from eventbuddy.data.redis import get_redis


def test_get_redis_returns_client_without_connecting():
    client = get_redis()
    # redis-py creates a lazy client; no connection until a command runs.
    assert client is not None
    assert get_redis() is client  # cached singleton
