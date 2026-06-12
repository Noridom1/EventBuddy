import httpx

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


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

    def create_channel(self, team_id: str, display_name: str, description: str = "") -> dict:
        url = f"/teams/{team_id}/channels"
        r = self._http.post(
            url,
            json={"displayName": display_name, "description": description},
            headers=self._headers(),
        )
        r.raise_for_status()
        return r.json()
