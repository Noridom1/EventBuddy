import base64

import httpx

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _share_token(url: str) -> str:
    """Encode a sharing URL into the Graph `shares/{token}` form (base64url, 'u!' prefix)."""
    b64 = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    return "u!" + b64


class GraphClient:
    """Thin typed wrapper over Microsoft Graph. All Microsoft writes go through here."""

    def __init__(self, token_provider, http=None):
        self._token = token_provider
        self._http = http or httpx.Client(base_url=GRAPH_BASE, timeout=30)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token.get_token()}",
            "Content-Type": "application/json",
        }

    def send_channel_message(self, team_id: str, channel_id: str, text: str) -> dict:
        url = f"/teams/{team_id}/channels/{channel_id}/messages"
        r = self._http.post(url, json={"body": {"content": text}}, headers=self._headers())
        r.raise_for_status()
        return r.json()

    def send_chat_message(self, chat_id: str, text: str) -> dict:
        url = f"/chats/{chat_id}/messages"
        r = self._http.post(url, json={"body": {"content": text}}, headers=self._headers())
        r.raise_for_status()
        return r.json()

    def send_mail(self, subject: str, body_html: str, to: list[str]) -> None:
        # ⚠ verify SDK: /me/sendMail vs /users/{id}/sendMail depending on app vs delegated perms.
        url = "/me/sendMail"
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": body_html},
                "toRecipients": [{"emailAddress": {"address": a}} for a in to],
            }
        }
        r = self._http.post(url, json=payload, headers=self._headers())
        r.raise_for_status()

    def send_channel_card(self, team_id: str, channel_id: str, card: dict) -> dict:
        """Post an Adaptive Card to a channel (used for proactive HITL proposals — e.g. the
        ingestion bulk-invite). The card rides as a message attachment referenced from the
        message body."""
        import json

        url = f"/teams/{team_id}/channels/{channel_id}/messages"
        attachment_id = "1"
        payload = {
            "body": {
                "contentType": "html",
                "content": f'<attachment id="{attachment_id}"></attachment>',
            },
            "attachments": [{
                "id": attachment_id,
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": json.dumps(card),
            }],
        }
        r = self._http.post(url, json=payload, headers=self._headers())
        r.raise_for_status()
        return r.json()

    def get_channel_files_folder(self, team_id: str, channel_id: str) -> tuple[str, str]:
        """Resolve a Teams channel's backing SharePoint folder → (drive_id, item_id)."""
        url = f"/teams/{team_id}/channels/{channel_id}/filesFolder"
        r = self._http.get(url, headers=self._headers())
        r.raise_for_status()
        data = r.json()
        return data["parentReference"]["driveId"], data["id"]

    def list_children(self, drive_id: str, item_id: str) -> list[dict]:
        """List the children (files + folders) of a drive item."""
        url = f"/drives/{drive_id}/items/{item_id}/children"
        r = self._http.get(url, headers=self._headers())
        r.raise_for_status()
        return r.json().get("value", [])

    def resolve_share_url(self, url: str) -> tuple[str, str]:
        """Resolve a SharePoint/OneDrive sharing URL → (drive_id, item_id) via /shares."""
        api = f"/shares/{_share_token(url)}/driveItem"
        r = self._http.get(api, headers=self._headers())
        r.raise_for_status()
        data = r.json()
        return data["parentReference"]["driveId"], data["id"]

    def get_drive_item_content(self, drive_id: str, item_id: str) -> tuple[bytes, str, str]:
        """Download a drive item → (bytes, filename, mime_type)."""
        meta = self._http.get(f"/drives/{drive_id}/items/{item_id}", headers=self._headers())
        meta.raise_for_status()
        m = meta.json()
        filename = m.get("name", "")
        mime = (m.get("file") or {}).get("mimeType", "")
        content = self._http.get(
            f"/drives/{drive_id}/items/{item_id}/content",
            headers=self._headers(), follow_redirects=True,
        )
        content.raise_for_status()
        return content.content, filename, mime

    def create_channel(self, team_id: str, display_name: str, description: str = "") -> dict:
        url = f"/teams/{team_id}/channels"
        r = self._http.post(
            url,
            json={"displayName": display_name, "description": description},
            headers=self._headers(),
        )
        r.raise_for_status()
        return r.json()
