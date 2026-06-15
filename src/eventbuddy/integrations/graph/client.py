import base64
import re
from urllib.parse import quote

import httpx

from eventbuddy.config import settings

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    """Collapse Teams message HTML to plain text (drop tags, unescape a few entities).
    Good enough for feeding channel discussion to the model — not a full HTML parser."""
    text = _TAG_RE.sub(" ", html or "")
    for ent, ch in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                    ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(ent, ch)
    return re.sub(r"\s+", " ", text).strip()


def _share_token(url: str) -> str:
    """Encode a sharing URL into the Graph `shares/{token}` form (base64url, 'u!' prefix)."""
    b64 = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    return "u!" + b64


class GraphClient:
    """Thin typed wrapper over Microsoft Graph. All Microsoft writes go through here."""

    def __init__(self, token_provider, http=None, sender=None, delegated=False):
        self._token = token_provider
        self._http = http or httpx.Client(base_url=GRAPH_BASE, timeout=30)
        # Mailbox to send as. Defaults to settings; overridable for tests.
        self._sender = sender if sender is not None else settings.graph_sender_upn
        # Plan 13 — when the token is a *delegated* (on-behalf-of-the-user) token, "me" resolves
        # to the signed-in user, so mail sends from *their* mailbox via /me/sendMail (no shared
        # bot mailbox / Application Access Policy). App-only tokens have no "me" and use
        # /users/{sender}/sendMail.
        self._delegated = delegated

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

    def get_my_id(self) -> str:
        """The signed-in user's directory id (delegated 'me'). Used to bind the caller as a
        member when creating a 1-1 chat."""
        r = self._http.get("/me?$select=id", headers=self._headers())
        r.raise_for_status()
        return r.json()["id"]

    @staticmethod
    def _as_user(d: dict) -> dict:
        return {
            "id": d.get("id"),
            "display_name": d.get("displayName") or d.get("userPrincipalName") or "",
            "upn": d.get("userPrincipalName") or d.get("mail") or "",
        }

    def _first_user_match(self, filter_expr: str, select: str) -> dict | None:
        """Run a `/users?$filter=…` query and return the first match as a user dict, or None."""
        url = f"/users?$filter={quote(filter_expr)}&$select={select}&$top=1"
        r = self._http.get(url, headers=self._headers())
        r.raise_for_status()
        vals = r.json().get("value", [])
        return self._as_user(vals[0]) if vals else None

    def resolve_user(self, alias_or_email: str) -> dict | None:
        """Resolve a corporate alias (mailNickname, e.g. 'phucnlt2') or a full email/UPN to a
        directory user → `{id, display_name, upn}`, or None when not found. Powers the generic
        `send_teams_message` tool. Needs the delegated `User.ReadBasic.All` scope. A miss returns
        None rather than raising, so the caller degrades to a clean "couldn't find them" message."""
        value = (alias_or_email or "").strip()
        if not value:
            return None
        select = "id,displayName,userPrincipalName,mail"
        if "@" in value:
            r = self._http.get(
                f"/users/{quote(value)}?$select={select}", headers=self._headers())
            if r.status_code == 200:
                return self._as_user(r.json())
            return self._first_user_match(f"mail eq '{value}'", select)
        # Bare alias → match on mailNickname; fall back to a UPN built from the corp domain.
        match = self._first_user_match(f"mailNickname eq '{value}'", select)
        if match is not None:
            return match
        if settings.corp_email_domain:
            upn = f"{value}@{settings.corp_email_domain}"
            r = self._http.get(
                f"/users/{quote(upn)}?$select={select}", headers=self._headers())
            if r.status_code == 200:
                return self._as_user(r.json())
        return None

    def create_one_on_one_chat(self, target_user_id: str) -> str:
        """Create (or return the existing) 1-1 chat between the signed-in user and
        `target_user_id`, returning its chat id. Delegated only — binds 'me' + the target as
        members. Needs the `Chat.Create` scope. Graph returns the existing chat if one already
        exists, so this is effectively get-or-create."""
        def _member(uid: str) -> dict:
            return {
                "@odata.type": "#microsoft.graph.aadUserConversationMember",
                "roles": ["owner"],
                "user@odata.bind": f"{GRAPH_BASE}/users('{uid}')",
            }

        payload = {
            "chatType": "oneOnOne",
            "members": [_member(self.get_my_id()), _member(target_user_id)],
        }
        r = self._http.post("/chats", json=payload, headers=self._headers())
        r.raise_for_status()
        return r.json()["id"]

    def send_mail(self, subject: str, body_html: str, to: list[str]) -> None:
        # Delegated (Plan 13): "me" is the signed-in user → POST /me/sendMail; the mail comes
        # from their own mailbox, no configured sender needed. App-only (legacy fallback): tokens
        # have no "me", so send as the configured mailbox via /users/{upn}/sendMail (Mail.Send
        # application, scoped by an Application Access Policy). Missing sender there → fail loud.
        if self._delegated:
            url = "/me/sendMail"
        else:
            if not self._sender:
                raise ValueError(
                    "send_mail: no sender mailbox configured (set GRAPH_SENDER_UPN)"
                )
            url = f"/users/{quote(self._sender)}/sendMail"
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

    def list_channel_messages(
        self, team_id: str, channel_id: str, limit: int = 30
    ) -> list[dict]:
        """Read a channel's recent top-level messages (Impl 3 — brainstorm). Returns
        `[{author, text, created}]` newest-first as Graph returns them, HTML stripped to
        plain text. Needs the `ChannelMessage.Read.Group` RSC permission. System messages and
        empty bodies are dropped. Requires the real `team_id` (not the tenant id)."""
        url = f"/teams/{team_id}/channels/{channel_id}/messages?$top={int(limit)}"
        r = self._http.get(url, headers=self._headers())
        r.raise_for_status()
        out: list[dict] = []
        for m in r.json().get("value", []):
            if m.get("messageType") and m["messageType"] != "message":
                continue  # skip systemEventMessage et al.
            text = _strip_html((m.get("body") or {}).get("content", "")).strip()
            if not text:
                continue
            author = (((m.get("from") or {}).get("user") or {}).get("displayName")) or "Unknown"
            out.append({"author": author, "text": text, "created": m.get("createdDateTime")})
        return out

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
