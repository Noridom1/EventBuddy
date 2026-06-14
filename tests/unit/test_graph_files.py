from eventbuddy.integrations.graph.client import GraphClient, _share_token


class _FakeToken:
    def get_token(self):
        return "tok-123"


def _resp(*, json_body=None, content=b"", status=200):
    return type("R", (), {
        "status_code": status,
        "content": content,
        "json": lambda self=None: json_body,
        "raise_for_status": lambda self=None: None,
    })()


class _FakeHttp:
    def __init__(self):
        self.calls = []

    def get(self, url, headers=None, follow_redirects=False):
        self.calls.append(("GET", url, follow_redirects))
        if url.endswith("/filesFolder"):
            return _resp(json_body={"id": "folder1", "parentReference": {"driveId": "drv1"}})
        if "/children" in url:
            return _resp(json_body={"value": [{"id": "f1", "name": "a.xlsx"},
                                               {"id": "d1", "name": "sub", "folder": {}}]})
        if "/driveItem" in url:  # /shares/{token}/driveItem
            return _resp(json_body={"id": "item9", "parentReference": {"driveId": "drvShare"}})
        if url.endswith("/content"):
            return _resp(content=b"BYTES")
        # item metadata
        return _resp(json_body={"name": "a.xlsx", "file": {"mimeType": "application/xlsx"}})

    def post(self, url, json=None, headers=None):
        self.calls.append(("POST", url, json))
        return _resp(json_body={"id": "msg1"})


def test_share_token_format():
    tok = _share_token("https://x/y.xlsx")
    assert tok.startswith("u!")
    assert "=" not in tok


def test_get_channel_files_folder():
    gc = GraphClient(token_provider=_FakeToken(), http=_FakeHttp())
    assert gc.get_channel_files_folder("team", "chan") == ("drv1", "folder1")


def test_list_children_returns_value():
    gc = GraphClient(token_provider=_FakeToken(), http=_FakeHttp())
    kids = gc.list_children("drv1", "folder1")
    assert {k["id"] for k in kids} == {"f1", "d1"}


def test_resolve_share_url():
    gc = GraphClient(token_provider=_FakeToken(), http=_FakeHttp())
    assert gc.resolve_share_url("https://x/y.xlsx") == ("drvShare", "item9")


def test_get_drive_item_content_returns_bytes_name_mime():
    http = _FakeHttp()
    gc = GraphClient(token_provider=_FakeToken(), http=http)
    content, name, mime = gc.get_drive_item_content("drv1", "f1")
    assert content == b"BYTES"
    assert name == "a.xlsx"
    assert mime == "application/xlsx"
    # the content fetch must follow redirects (Graph 302s to a download URL)
    assert any(c[0] == "GET" and c[1].endswith("/content") and c[2] for c in http.calls)


def test_send_channel_card_posts_adaptive_attachment():
    http = _FakeHttp()
    gc = GraphClient(token_provider=_FakeToken(), http=http)
    gc.send_channel_card("team", "chan", {"type": "AdaptiveCard"})
    method, url, body = http.calls[-1]
    assert method == "POST"
    assert "teams/team/channels/chan/messages" in url
    assert body["attachments"][0]["contentType"] == "application/vnd.microsoft.card.adaptive"
