# EventBuddy — Teams Onboarding Request for IT (Entra Admin)

**To:** IT / Microsoft Entra administrator
**From:** EventBuddy developer team
**Date:** 2026-06-15
**Purpose:** register an internal Microsoft Teams bot ("EventBuddy") in our tenant so it can be piloted safely.

The four items you asked for — **name, endpoint, scope, permissions** — are in §1; the Graph permission detail is in §2. **All Graph access is delegated** (the bot acts on behalf of the signed-in user) — no tenant-wide application permissions are requested.

---

## 1. The four details you asked for

| Item | Value |
|---|---|
| **App / bot name** | `EventBuddy` |
| **Messaging endpoint** | `https://endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn/api/messages` |
| **Endpoint host (for validDomains)** | `endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn` |
| **Install scope** | `personal` (1:1 chat) + `team` (channel) |
| **Account type** | **Single-tenant** (this organization only) |
| **Graph permissions** | **Delegated only** — see §2. |

The endpoint is already live (public HTTPS). You can sanity-check it returns a response at the host root before wiring.

---

## 2. Microsoft Graph permissions (delegated)

The bot signs the user in via **Teams SSO** and acts **on its behalf**, so every Graph call is scoped to **what that user can already access** — it can never reach tenant data the user can't (e.g. someone else's OneDrive). The bot's chat replies need no Graph permission at all.

| Capability | Delegated scope | Note |
|---|---|---|
| Sign-in / identify the caller (SSO) | `openid`, `profile`, `email`, `User.Read` | Teams SSO baseline; declared via `webApplicationInfo` in the manifest |
| Keep working for scheduled sends | `offline_access` | Refresh token so background reminder/feedback jobs can act later as the user who scheduled them |
| Create an event's Teams channel | `Channel.Create` | As the user (must be a team member/owner) |
| Read & download channel files (SharePoint) | `Files.Read.All` + `Sites.Read.All` | **Delegated** — only files the user can already open |
| Resolve a member's corp email → Teams id | `User.ReadBasic.All` | Map roster email → Teams/AAD id so invited members are recognised |
| Send notification / registration / reminder / feedback email | `Mail.Send` | Sends **as the signed-in user's mailbox** (no shared bot mailbox) |
| Read channel discussion | `ChannelMessage.Read.All` | As the user |
| Post reminders / announcements / confirm cards into a channel | `ChannelMessage.Send` | As the user (or via Bot Framework proactive — no Graph) |

> These are **delegated** scopes — the app holds **no standalone tenant-wide access**; access is always bounded by the signed-in user. An admin may **grant admin consent once** to these scopes (so users aren't individually prompted), or leave per-user consent on. Setup also needs an **OAuth connection / SSO** configured on the Azure Bot + Entra app (expose an `access_as_user` API scope).

---

## 3. Why scoped testing in production Teams is safe

A Teams bot only ever sees chats/channels **it's explicitly added to**. With **delegated** Graph access, it additionally only ever touches data the **signed-in user** can already access — the bot has no credentials of its own that reach the tenant at large. Installed only into a **test team we own**, with custom-app upload enabled just for our account, it stays **invisible to the rest of the org**. Org-wide publishing comes only **after** the sandbox test passes.

**One honest note:** scheduled reminder/feedback emails fire later with no one signed in, so they reuse a **stored refresh token** (`offline_access`) and act *as the host who set them up*. That token can expire or be revoked (password/MFA change), in which case background sends pause until the host re-authenticates — a deliberate trade for keeping the bot least-privileged.

---

*Companion: [EventBuddy-Teams-Integration-Guide.md](EventBuddy-Teams-Integration-Guide.md) and the app package in [`teams-app/`](../teams-app/).*
