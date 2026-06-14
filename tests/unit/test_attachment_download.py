"""Impl 4 — `fetch_attachment_bytes`: Teams `download_url` via plain HTTP (no Graph), a share
link / `content_url` via Graph, and clean degradation (returns None, never raises)."""
import httpx

from eventbuddy.capabilities import attachments
from eventbuddy.capabilities.attachments import fetch_attachment_bytes


class _FakeGraph:
    def __init__(self):
        self.resolved = None

    def resolve_share_url(self, url):
        self.resolved = url
        return ("drive-1", "item-1")

    def get_drive_item_content(self, drive_id, item_id):
        return b"col\nval\n", "linked.csv", "text/csv"


def test_fetch_via_download_url(monkeypatch):
    def fake_get(url, timeout=30, follow_redirects=True):
        return httpx.Response(200, content=b"Email\na@x.com\n", request=httpx.Request("GET", url))

    monkeypatch.setattr(attachments.httpx, "get", fake_get)
    out = fetch_attachment_bytes(
        {"name": "roster.csv", "download_url": "https://teams/dl"}, graph=None
    )
    assert out == ("roster.csv", b"Email\na@x.com\n")


def test_fetch_via_download_url_needs_no_graph(monkeypatch):
    # A Teams upload's downloadUrl is pre-authenticated — Graph must not be touched.
    monkeypatch.setattr(
        attachments.httpx, "get",
        lambda url, timeout=30, follow_redirects=True: httpx.Response(
            200, content=b"x", request=httpx.Request("GET", url)),
    )
    g = _FakeGraph()
    fetch_attachment_bytes({"name": "f.csv", "download_url": "https://dl"}, graph=g)
    assert g.resolved is None


def test_fetch_via_share_link_uses_graph():
    g = _FakeGraph()
    url = "https://contoso.sharepoint.com/:x:/r/share"
    out = fetch_attachment_bytes({"name": "", "content_url": url}, graph=g)
    assert out == ("linked.csv", b"col\nval\n")
    assert g.resolved == url


def test_fetch_degrades_on_http_error(monkeypatch):
    def boom(url, timeout=30, follow_redirects=True):
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(attachments.httpx, "get", boom)
    assert fetch_attachment_bytes({"download_url": "https://dl"}) is None


def test_fetch_share_link_without_graph_returns_none():
    url = "https://contoso.sharepoint.com/:x:/r/share"
    assert fetch_attachment_bytes({"content_url": url}, graph=None) is None


def test_fetch_via_data_uri_decodes_inline(monkeypatch):
    # Desktop Bot Framework Emulator inlines an attached file as a base64 data URI — decoded
    # with no network (Graph must not be touched).
    import base64
    g = _FakeGraph()
    payload = base64.b64encode(b"Email\na@x.com\n").decode()
    out = fetch_attachment_bytes(
        {"name": "roster.csv", "content_url": f"data:text/csv;base64,{payload}"}, graph=g
    )
    assert out == ("roster.csv", b"Email\na@x.com\n")
    assert g.resolved is None  # no Graph call for a data URI


def test_fetch_non_share_content_url_uses_direct_get(monkeypatch):
    # An Emulator-served localhost attachment URL is fetched directly, not via Graph.
    g = _FakeGraph()
    monkeypatch.setattr(
        attachments.httpx, "get",
        lambda url, timeout=30, follow_redirects=True: httpx.Response(
            200, content=b"Email\nb@x.com\n", request=httpx.Request("GET", url)),
    )
    out = fetch_attachment_bytes(
        {"name": "r.csv", "content_url": "http://localhost:9000/v3/attachments/x"}, graph=g
    )
    assert out == ("r.csv", b"Email\nb@x.com\n")
    assert g.resolved is None  # localhost URL is not a share link


def test_fetch_oversized_download_rejected(monkeypatch):
    big = b"x" * (attachments.MAX_BYTES + 1)
    monkeypatch.setattr(
        attachments.httpx, "get",
        lambda url, timeout=30, follow_redirects=True: httpx.Response(
            200, content=big, request=httpx.Request("GET", url)),
    )
    assert fetch_attachment_bytes({"download_url": "https://dl"}) is None
