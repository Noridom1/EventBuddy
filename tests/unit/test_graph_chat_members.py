"""Impl 8 — GraphClient chat/channel member + chat file methods.

Group chat / 1-1 DM members come from /chats/{id}/members; channel members from the team
channel endpoint; chat files are `reference` attachments scraped from chat messages."""
from eventbuddy.integrations.graph.client import GraphClient


class _FakeToken:
    def get_token(self):
        return "tok-123"


def _resp(json_body):
    return type("R", (), {
        "status_code": 200,
        "json": lambda self=None: json_body,
        "raise_for_status": lambda self=None: None,
    })()


class _FakeHttp:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, headers=None):
        self.calls.append(url)
        for substr, body in self.routes.items():
            if substr in url:
                return _resp(body)
        raise AssertionError(f"unrouted GET {url}")


def test_list_chat_members_maps_fields():
    http = _FakeHttp({"/chats/": {"value": [
        {"userId": "aad-1", "displayName": "Ann Lee", "email": "ann@x.com"},
        {"userId": "aad-2", "displayName": "Bo", "userPrincipalName": "bo@x.com"},  # email→UPN
        {"id": "guest-1", "displayName": "Guest"},  # no userId/email → kept with empties
    ]}})
    gc = GraphClient(token_provider=_FakeToken(), http=http)
    members = gc.list_chat_members("19:abc@thread.v2")
    assert members[0] == {"id": "aad-1", "display_name": "Ann Lee", "email": "ann@x.com"}
    assert members[1]["email"] == "bo@x.com"  # falls back to UPN
    assert members[2] == {"id": "guest-1", "display_name": "Guest", "email": ""}
    assert "/chats/" in http.calls[0] and "/members" in http.calls[0]


def test_list_channel_members_hits_team_channel_endpoint():
    http = _FakeHttp({"/teams/t1/channels/c1/members": {"value": [
        {"userId": "aad-9", "displayName": "Cy", "email": "cy@x.com"},
    ]}})
    gc = GraphClient(token_provider=_FakeToken(), http=http)
    members = gc.list_channel_members("t1", "c1")
    assert members == [{"id": "aad-9", "display_name": "Cy", "email": "cy@x.com"}]
    assert "/teams/t1/channels/c1/members" in http.calls[0]


def test_list_chat_files_extracts_reference_attachments_deduped():
    http = _FakeHttp({"/messages": {"value": [
        {"attachments": [
            {"contentType": "reference", "name": "agenda.docx",
             "contentUrl": "https://x/agenda.docx"},
            {"contentType": "messageReference"},  # not a file → skipped
        ]},
        {"attachments": [
            {"contentType": "reference", "name": "agenda.docx",
             "contentUrl": "https://x/agenda.docx"},  # dup url → skipped
            {"contentType": "reference", "name": "budget.xlsx",
             "contentUrl": "https://x/budget.xlsx"},
        ]},
        {"body": {"content": "no attachments here"}},  # no attachments key → fine
    ]}})
    gc = GraphClient(token_provider=_FakeToken(), http=http)
    files = gc.list_chat_files("19:abc@thread.v2")
    assert files == [
        {"name": "agenda.docx", "url": "https://x/agenda.docx"},
        {"name": "budget.xlsx", "url": "https://x/budget.xlsx"},
    ]
    assert "$top=50" in http.calls[0]
