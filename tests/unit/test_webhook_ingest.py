from eventbuddy.ingestion.webhook import handle_notifications


class _FakeRedis:
    def __init__(self):
        self.keys = {}

    def set(self, key, val, nx=False, ex=None):
        if nx and key in self.keys:
            return False
        self.keys[key] = val
        return True


def _notif(item_id, etag="v1"):
    return {"value": [{"resourceData": {"id": item_id, "eTag": etag}, "changeType": "updated"}]}


def test_dedup_processes_each_change_once():
    redis = _FakeRedis()
    ingested = []
    body = _notif("item-1")
    handle_notifications(body, redis_client=redis, ingest=ingested.append)
    handle_notifications(body, redis_client=redis, ingest=ingested.append)  # re-delivery
    assert len(ingested) == 1


def test_new_etag_is_processed_again():
    redis = _FakeRedis()
    ingested = []
    handle_notifications(_notif("item-1", "v1"), redis_client=redis, ingest=ingested.append)
    handle_notifications(_notif("item-1", "v2"), redis_client=redis, ingest=ingested.append)
    assert len(ingested) == 2


def test_handles_empty_body_without_ingest():
    # No 'value', no redis, no ingest hook — must not raise and returns 0.
    assert handle_notifications({}) == 0


def test_redis_down_falls_through_best_effort():
    class _Boom:
        def set(self, *a, **k):
            raise RuntimeError("redis down")

    ingested = []
    n = handle_notifications(_notif("x"), redis_client=_Boom(), ingest=ingested.append)
    assert n == 1 and len(ingested) == 1
