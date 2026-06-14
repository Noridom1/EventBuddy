"""Download bytes for an incoming file attachment (Impl 4).

Delivery modes, in priority order:
  • a Teams upload's pre-authenticated `download_url` → a plain HTTP GET (no Graph);
  • a `content_url` that is a `data:` URI → decoded inline (the **desktop Bot Framework
    Emulator** inlines attached files this way — no network);
  • a `content_url` on a SharePoint/OneDrive host → resolved + downloaded via Microsoft Graph
    (the same path Impl 2 uses for `ingest_event_files`);
  • any other http(s) `content_url` → a plain HTTP GET (e.g. an Emulator-served localhost URL).

Returns `(filename, bytes)` or `None` — it never raises, so the caller emits a clean
degradation message. The size cap bounds an accidental huge download (a roster is small)."""
import base64
from urllib.parse import unquote_to_bytes, urlparse

import httpx

from eventbuddy.common.logging import get_logger

log = get_logger("capabilities.attachments")

MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_SHARE_HOSTS = ("sharepoint.com", "onedrive.live.com", "1drv.ms")


def _cap(name: str, data: bytes):
    if len(data) > MAX_BYTES:
        log.warning(f"attachment {name} exceeds {MAX_BYTES} bytes — skipping")
        return None
    return name, data


def _http_get(url: str, name: str, timeout: int):
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001 — degrade, never raise
        log.warning(f"attachment download failed for {name} ({type(e).__name__}: {e})")
        return None
    return _cap(name, r.content)


def _decode_data_uri(uri: str, name: str):
    """Decode a `data:[<mediatype>][;base64],<data>` URI to bytes (desktop Emulator uploads)."""
    try:
        header, _, payload = uri.partition(",")
        if not payload:
            return None
        data = base64.b64decode(payload) if ";base64" in header else unquote_to_bytes(payload)
    except Exception as e:  # noqa: BLE001
        log.warning(f"data-uri decode failed for {name} ({type(e).__name__}: {e})")
        return None
    return _cap(name, data)


def _looks_like_share_link(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(h in host for h in _SHARE_HOSTS)


def fetch_attachment_bytes(descriptor: dict, *, graph=None, timeout: int = 30):
    """Resolve a descriptor `{name, download_url?, content_url?}` to `(filename, bytes)`."""
    descriptor = descriptor or {}
    name = descriptor.get("name") or "attachment"
    download_url = descriptor.get("download_url")
    content_url = descriptor.get("content_url")

    if download_url:
        return _http_get(download_url, name, timeout)

    if content_url:
        if content_url.startswith("data:"):
            return _decode_data_uri(content_url, name)
        if _looks_like_share_link(content_url):
            if graph is None:
                return None
            try:
                drive_id, item_id = graph.resolve_share_url(content_url)
                data, filename, _mime = graph.get_drive_item_content(drive_id, item_id)
            except Exception as e:  # noqa: BLE001
                log.warning(f"share-link download failed for {content_url} "
                            f"({type(e).__name__}: {e})")
                return None
            return _cap(filename or name, data)
        # Any other http(s) URL (e.g. an Emulator-served localhost attachment) → direct GET.
        return _http_get(content_url, name, timeout)

    return None
