# EventBuddy — Microsoft Graph Delegated Permissions

All scopes are **delegated** — the bot acts on behalf of the signed-in user, bounded by what that
user can already access. No tenant-wide application permissions are requested.

**Status legend:** ✅ Granted · 🆕 To request (not yet granted)

| Delegated scope | Capability it unlocks | Status |
|---|---|---|
| `openid` | SSO sign-in | ✅ Granted |
| `profile` | View user's basic profile | ✅ Granted |
| `email` | View user's email address | ✅ Granted |
| `User.Read` | Sign in and read the caller's profile | ✅ Granted |
| `User.ReadBasic.All` | Resolve corp email → Teams/AAD id | ✅ Granted |
| `offline_access` | Refresh token for scheduled/background sends | ✅ Granted |
| `Channel.Create` | Create an event's Teams channel | ✅ Granted |
| `ChannelMessage.Read.All` | Read Team channel messages | ✅ Granted |
| `ChannelMessage.Send` | Post into a Team channel | ✅ Granted |
| `Chat.Create` | Get-or-create a 1-1 chat | ✅ Granted |
| `ChatMessage.Send` | Send a 1-1 / group chat message | ✅ Granted |
| `Mail.Send` | Send email as the signed-in user | ✅ Granted |
| `Files.Read.All` | Read & download files the user can access | ✅ Granted |
| `Sites.Read.All` | Read items in SharePoint site collections | ✅ Granted |
| `Chat.Read` | Read group-chat / DM messages to find shared files (`GET /chats/{id}/messages`) | 🆕 To request |
| `ChatMember.Read` | List group-chat / DM members (`GET /chats/{id}/members`) | 🆕 To request |
| `ChannelMember.Read.All` | List Team channel members (`GET /teams/{id}/channels/{cid}/members`) | 🆕 To request |
| `Files.ReadWrite.All` | Read **and edit** files the user can access — edit/upload SharePoint & OneDrive files (supersedes `Files.Read.All`) | 🆕 To request |
| `Sites.ReadWrite.All` | Edit items in SharePoint site collections (supersedes `Sites.Read.All`) | 🆕 To request |
