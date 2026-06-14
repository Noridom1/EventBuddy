"""Graph change-notification handling for document ingestion (architecture §7.2).

Graph posts file-change notifications to `/api/webhooks/graph`. We **dedup** each one via
Redis (re-delivery is normal) and hand it to an `ingest` callback. NOTE: mapping a drive-item
notification back to an EventBuddy `event_id` requires subscription metadata captured at
subscription-creation time, which is out of scope for this implementation (subscriptions are
created manually for the demo). So the wired default does dedup + log only; the **on-demand
channel-files sync** (`capabilities/channel_files.py`) is the fully-working ingest path. The
`ingest` hook is injectable so this stays unit-testable and ready to wire when subscription
mapping exists."""
from eventbuddy.common.logging import get_logger

log = get_logger("ingestion.webhook")

_DEDUP_TTL = 3600


def handle_notifications(body: dict, *, redis_client=None, ingest=None) -> int:
    """Process a Graph notification batch. Returns the count of *new* notifications handled
    (after dedup). Best-effort — never raises (a 5xx would make Graph retry forever)."""
    notifications = (body or {}).get("value") or []
    handled = 0
    for n in notifications:
        rd = n.get("resourceData") or {}
        item_id = rd.get("id") or n.get("resource")
        if not item_id:
            continue
        marker = f"ingest:{item_id}:{rd.get('eTag') or n.get('changeType', '')}"
        if redis_client is not None:
            try:
                if not redis_client.set(marker, "1", nx=True, ex=_DEDUP_TTL):
                    continue  # already seen this exact change
            except Exception as e:  # noqa: BLE001 — Redis down: fall through (best-effort)
                log.warning(f"webhook dedup unavailable ({type(e).__name__}: {e})")
        if ingest is not None:
            try:
                ingest(n)
            except Exception as e:  # noqa: BLE001
                log.warning(f"webhook ingest failed ({type(e).__name__}: {e})")
        else:
            log.info(f"graph notification {item_id} acked (ingest mapping not wired)")
        handled += 1
    return handled
