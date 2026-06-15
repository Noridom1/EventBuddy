# EventBuddy — Microsoft Graph Delegated Permissions Ledger

**Purpose.** A single running list of the **delegated** Microsoft Graph scopes EventBuddy needs,
so newly-required scopes can accumulate here across implementations and be **requested from IT in
one batch** rather than piecemeal. All access is **delegated** (the bot acts on behalf of the
signed-in user, bounded by what that user can already access) — no tenant-wide application
permissions are ever requested.

**How to use this file.** Each implementation that needs a new scope appends a row to §2 and a
note to §3 (the implementation log). When you're ready to talk to IT, send them everything in §1
that is still **🆕 Pending** — that's the delta since the last request. After IT grants a batch,
flip those rows to **✅ Granted** and record the date.

**Status legend:** ✅ Granted · 📨 Requested (awaiting grant) · 🆕 Pending (not yet sent to IT)

> Companion: the formal request narrative lives in
> [EventBuddy-IT-Onboarding-Request-Compact.md](EventBuddy-IT-Onboarding-Request-Compact.md)
> (EN) / [EventBuddy-IT-Onboarding-Request-VI-Compact.md](EventBuddy-IT-Onboarding-Request-VI-Compact.md) (VI).
> This ledger is the machine-readable, cumulative source of truth for *which scopes* are needed.

---

## 1. Pending request — the next batch to send IT

> These scopes are needed by shipped/merged code but **not yet granted**. Copy this block to IT.

| Delegated scope | Capability it unlocks | Needed by |
|---|---|---|
| `ChatMember.Read` | List the members of a group chat / 1-1 DM (`GET /chats/{id}/members`) | Impl 8 — `list_members` |
| `Chat.Read` | Read chat messages to find files shared in a group chat / DM (`GET /chats/{id}/messages`) | Impl 8 — `list_files` (chat scope) |
| `ChannelMember.Read.All` | List the members of a Team channel (`GET /teams/{id}/channels/{cid}/members`) | Impl 8 — `list_members` (channel scope) |

*(`Files.Read.All` + `Sites.Read.All`, needed to download the OneDrive driveItems behind chat
files, are already granted — see §2 — so no new file-download scope is required for Impl 8.)*

---

## 2. Master ledger — every delegated scope, cumulative

| Scope | Capability | Status | Source | Note |
|---|---|---|---|---|
| `openid` | SSO sign-in | ✅ Granted | Onboarding | Teams SSO baseline (`webApplicationInfo`) |
| `profile` | SSO sign-in | ✅ Granted | Onboarding | Teams SSO baseline |
| `email` | SSO sign-in | ✅ Granted | Onboarding | Teams SSO baseline |
| `User.Read` | Identify the caller | ✅ Granted | Onboarding | Teams SSO baseline |
| `offline_access` | Refresh token for scheduled sends | ✅ Granted | Onboarding | Background reminder/feedback jobs act as the host who scheduled them |
| `Channel.Create` | Create an event's Teams channel | ✅ Granted | Onboarding | As the user (team member/owner) |
| `Files.Read.All` | Read & download files | ✅ Granted | Onboarding (Impl 2/5) | Delegated — only files the user can open. **Also covers chat-file download (Impl 8).** |
| `Sites.Read.All` | Read SharePoint sites/links | ✅ Granted | Onboarding (Impl 2/5) | Resolve SharePoint/OneDrive share links |
| `User.ReadBasic.All` | Resolve corp email → Teams/AAD id | ✅ Granted | Onboarding (Plan 13b) | Resolution step not yet implemented in code |
| `Mail.Send` | Send email as the signed-in user | ✅ Granted | Onboarding (Impl 1/4/7) | From the user's own mailbox, no shared mailbox |
| `ChannelMessage.Read.All` | Read channel discussion | ✅ Granted | Onboarding (Impl 3) | As the user |
| `ChannelMessage.Send` | Post into a channel | ✅ Granted | Onboarding (Impl 1) | As the user (or Bot Framework proactive) |
| `Chat.Create` | Get-or-create a 1-1 chat | ✅ Granted | Impl 7 | `send_teams_message` to a colleague (assumed within the granted Chat.* set — confirm) |
| `ChatMessage.Send` | Send a 1-1 Teams message | ✅ Granted | Impl 7 | `send_teams_message` (assumed within granted set — confirm) |
| `ChatMember.Read` | List group-chat / DM members | 🆕 Pending | Impl 8 | `GET /chats/{id}/members` |
| `Chat.Read` | Read chat messages (find shared files) | 🆕 Pending | Impl 8 | `GET /chats/{id}/messages` for file attachments |
| `ChannelMember.Read.All` | List Team channel members | 🆕 Pending | Impl 8 | `GET /teams/{id}/channels/{cid}/members` |

> **Note on the Impl 7 `Chat.*` rows:** `send_teams_message` (1-1 DM send) needs `Chat.Create` +
> `ChatMessage.Send`. These were not in the original onboarding §2 list; if IT granted the 12
> onboarding scopes verbatim, **confirm these two are present** or add them to the next batch.

---

## 3. Implementation log (append newest on top)

### Impl 8 — Scope-aware files & members (group chat + 1-1 DM) — 2026-06-15
- **New scopes:** `ChatMember.Read`, `Chat.Read`, `ChannelMember.Read.All`.
- **Reuses (already granted):** `Files.Read.All`, `Sites.Read.All` (download the OneDrive
  driveItems behind chat files).
- **Why:** the bot was tested in a *group chat* but its file/member tools were hardwired to a
  *Team channel*'s SharePoint backing. Group chats and DMs have no SharePoint — members come from
  `/chats/{id}/members` and files are message attachments resolved from OneDrive.
- **Degradation:** every new tool returns a clean message (never raises) when its scope isn't
  consented yet, so shipping ahead of the grant is safe — the features are simply dark until IT
  approves.

### Impl 7 — Generic send tools — (date n/a)
- Used `Chat.Create` + `ChatMessage.Send` for `send_teams_message`; `Mail.Send` for `send_email`.
  See the confirm note in §2.

### Onboarding (Plan 13, delegated-first migration) — 2026-06-15
- Original batch of 12 delegated scopes requested + granted. See §2 rows marked "Onboarding".
