# EventBuddy → Microsoft Teams Integration Guide

**Audience:** you (the EventBuddy developer) + your IT / Microsoft Entra administrator.
**Goal:** get EventBuddy running inside your corporation's Microsoft Teams tenant, safely and incrementally.
**Status as of 2026-06-14:** bot code is complete and runs locally / on AgentBase. Bot Framework credentials (`MICROSOFT_APP_ID` / `MICROSOFT_APP_PASSWORD` / tenant) and Graph credentials are **empty** — so today the bot runs auth-disabled and degrades gracefully. This document is the plan to fill that gap.

---

## 0. TL;DR — what you hand IT

IT (as Entra admin) asked for the **endpoint, name, scope, permissions**. Here is the precise answer; the rest of this doc explains *why* each one matters.

| What IT asked | What to give them | Notes |
|---|---|---|
| **Name** | `EventBuddy` (bot display name + Teams app name) | Cosmetic; appears in Teams. Keep it consistent across the Entra app, Azure Bot resource, and Teams manifest. |
| **Endpoint** | `https://<your-agentbase-endpoint>/api/messages` | Must be **public HTTPS with a valid TLS cert**. This is the only inbound URL Teams calls. Get the host from `make endpoint`. |
| **Scope** (Teams install scope) | `personal` + `team` (and optionally `groupChat`) | EventBuddy works in 1:1 DMs (`dm:` threads) and in channels (`event:` threads). See §3. |
| **Scope** (OAuth/Graph) | Microsoft Graph **application** permissions — see §5 table | This is the *other* meaning of "scope"; don't confuse it with install scope. |
| **Permissions** | Bot Framework registration (no special perms) + Graph perms in §5 + (optionally) RSC perms in the manifest | The bot's *chat* reply path needs no Graph perms; only the proactive/channel/files/mail features do. |

There is a ready-to-paste request for IT at the **end of this document (§10)**.

---

## 1. The mental model — five layers you must understand

A Teams bot is **not** "Teams calls my server directly." Five distinct layers sit between a user typing in Teams and your FastAPI `POST /api/messages` handler. Understanding them tells you exactly who owns what.

```
┌─────────────────────────────────────────────────────────────────────┐
│ (5) Teams App Package (manifest.json + 2 icons, zipped)               │
│     "How the app shows up in Teams, and what it's allowed to do"      │
│     → uploaded to Teams / Teams Admin Center                          │
├─────────────────────────────────────────────────────────────────────┤
│ (4) Microsoft Teams client + Teams platform                          │
│     User types → Teams routes to the bot's registered channel         │
├─────────────────────────────────────────────────────────────────────┤
│ (3) Bot Framework / Azure Bot Service connector                       │
│     The relay. Receives the Teams activity, signs a JWT, and POSTs     │
│     it to your messaging endpoint. Also where the Teams *channel* is   │
│     turned on. This is a real Azure resource ("Azure Bot").           │
├─────────────────────────────────────────────────────────────────────┤
│ (2) Microsoft Entra ID App Registration                               │
│     The bot's *identity*: Application (client) ID + secret.           │
│     The connector uses it to sign requests; your app uses it to       │
│     validate them (and to get Graph tokens). Owned by IT.             │
├─────────────────────────────────────────────────────────────────────┤
│ (1) Your app — EventBuddy on AgentBase                                │
│     FastAPI `POST /api/messages` → CloudAdapter validates the JWT →    │
│     EventBuddyBot → LangGraph agent. (Already built.)                  │
└─────────────────────────────────────────────────────────────────────┘
```

### What each layer *is*, concretely

1. **Your app (already done).** [api/messages.py](../src/eventbuddy/api/messages.py) hands the raw activity to a `CloudAdapter` ([bot/adapter.py](../src/eventbuddy/bot/adapter.py)). The adapter is built from `ConfigurationBotFrameworkAuthentication`, which reads `APP_ID`/`APP_PASSWORD`. **With empty creds the adapter is auth-disabled** (fine for the emulator, *not* safe for production). Filling the creds turns on real JWT validation of every inbound request.

2. **Entra ID App Registration — the bot's identity.** One Application (client) ID + one client secret (or certificate). The Bot Framework connector signs the activities it sends you with this identity; your `CloudAdapter` validates them against it. This is the single most important artifact and **IT owns it** (they're the Entra admin). It also doubles as the OAuth client used to fetch Microsoft Graph tokens (or you can use a *separate* app for Graph — see §4).

3. **Azure Bot Service resource ("Azure Bot").** A resource in an Azure subscription that ties your **Entra App ID** to your **messaging endpoint** and exposes the **Microsoft Teams channel**. This is what actually makes Teams able to reach you. Creating it needs an Azure subscription + Contributor rights — usually IT, or you if you have a subscription. *Note:* it is possible to register a bot **without** a full Azure subscription via the Teams **Developer Portal** (dev.teams.microsoft.com) for test scenarios, but the production-grade path is an Azure Bot resource.

4. **Teams platform / channel.** Once layer 3's Teams channel is enabled, Teams knows how to deliver activities for your bot ID to the connector, which relays them to your endpoint. Nothing for you to configure here directly.

5. **Teams App Package (the manifest).** A zip of `manifest.json` + a 192×192 color icon + a 32×32 outline icon. The manifest declares: the app id, the **bot id (= your Entra App ID)**, the install **scopes** (personal/team/groupChat), bot commands, **valid domains**, optional **SSO** (`webApplicationInfo`), and optional **RSC permissions** (`authorization.permissions.resourceSpecific`). This package is what gets uploaded/sideloaded/published. *This is the part you author and IT approves.*

### The single most common confusion: **two meanings of "scope"**
- **Install scope** = *where* the app can be added: `personal` (1:1 chat with the bot), `team` (a channel), `groupChat`. Declared in the manifest.
- **Permission scope** = *what data* the app can touch: Microsoft Graph permissions / RSC permissions. Granted by admin consent and/or by the team owner at install time.

When IT says "scope," clarify which they mean. You almost certainly need to answer **both** (see §0 table).

---

## 2. Who does what (you vs IT)

| Step | Owner | Why |
|---|---|---|
| Create the **Entra app registration** (App ID + secret) | **IT** | They are the Entra admin; app registration may be locked down for non-admins. |
| Decide **single-tenant vs multi-tenant** | IT (with you) | For an internal corporate bot, **single-tenant** (this org only) is the secure default. |
| Create the **Azure Bot resource** + enable **Teams channel** + set **messaging endpoint** | IT (or you, if you have an Azure subscription) | Needs an Azure subscription. The App ID from the step above is plugged in here. |
| Grant **admin consent** for Graph application permissions | **IT only** | Application permissions and protected Graph APIs require a Global/Privileged Role admin. |
| Author the **Teams app manifest** + icons + zip | **You** | It's part of the app; you know the commands/scopes/domains. |
| **Enable custom-app upload (sideloading)** for your test account/team | **IT** | Off by default in most tenants. Needed so you can test in real Teams. |
| Upload/sideload the app to a **test team** | You | Once IT enables it. |
| **Publish org-wide** (Teams Admin Center) when ready | IT | Org-wide rollout is an admin action. |
| Fill `.env` creds on AgentBase + redeploy | You | `MICROSOFT_APP_ID/PASSWORD/TENANT_ID`, `GRAPH_*`, `MICROSOFT_TEAM_ID`. |

---

## 3. Teams install scope — what EventBuddy actually uses

EventBuddy's memory and routing are **scope-aware** (see [activity_router.py](../src/eventbuddy/bot/activity_router.py) `_scope_and_team`):

- **`personal` (1:1 DM)** → thread id `dm:{user_id}`. Used for provisioning events from a DM, focusing on an event, asking the agent things privately. **This is the scope you can test most easily and safely first.**
- **`team` (channel)** → thread id `event:{channel_id}`. Used for per-event channel discussion, reminders, reports, channel ingestion. Requires the bot to be installed in a team and (for reading/posting via Graph) the relevant permissions.
- **`groupChat`** → treated as `personal` by the code (no team/SharePoint backing). Optional in the manifest.

**Recommendation:** declare `personal` + `team` in the manifest. Add `groupChat` only if you want the bot usable in ad-hoc group chats.

---

## 4. The two identities — Bot Framework app vs Graph app

EventBuddy's config has **two separate credential sets** ([config.py](../src/eventbuddy/config.py)):

- `MICROSOFT_APP_ID` / `MICROSOFT_APP_PASSWORD` / `MICROSOFT_APP_TENANT_ID` → the **Bot Framework** identity (layer 2/3). Used to validate inbound activities and to send replies through the connector.
- `GRAPH_TENANT_ID` / `GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET` → the **Microsoft Graph** identity (client-credentials), used by [integrations/graph/client.py](../src/eventbuddy/integrations/graph/client.py) for channel creation, channel message read/send, SharePoint files, and mail.

You have two valid options:
1. **One app for both** (simplest): use the same Entra app for Bot Framework *and* Graph; set the `GRAPH_*` values equal to the `MICROSOFT_APP_*` values. The app then needs both the bot registration *and* the Graph permissions in §5.
2. **Two apps** (cleaner separation of duties): a thin app for the bot identity, and a separate app holding the Graph permissions. Useful if IT wants the high-privilege Graph consent isolated from the bot identity.

Discuss with IT; **option 1 is fine for the hackathon/pilot**, option 2 is the "production hygiene" choice.

> **Important:** never put the App ID, role, or scope into tool arguments. EventBuddy already enforces this — identity/role/scope come from the server-built `RequestContext`, not from the model. Keep it that way (cross-cutting security rule 2 in CLAUDE.md).

---

## 5. Permissions — the exact Graph permission set

EventBuddy's **chat reply path needs no Graph permissions** — replies go back through the Bot Framework connector, not Graph. Graph permissions are only needed for the proactive / channel / files / mail features. Here is the full set, mapped to the code that uses it:

| Graph permission (application) | Used by | Feature | Sensitivity |
|---|---|---|---|
| `Channel.Create.All` *(or `Group.ReadWrite.All`)* | `create_channel` | Provision an event's Teams channel | High |
| `ChannelMessage.Read.All` *(or RSC `ChannelMessage.Read.Group`)* | `list_channel_messages` | Channel brainstorm / ingestion | **Protected** — needs Microsoft approval for app perm; RSC avoids that |
| `ChannelMessage.Send` is **not** an app permission — posting to a channel as an app is via RSC `ChannelMessage.Send.Group` *(protected)* | `send_channel_message`, `send_channel_card` | Proactive HITL cards / reminders in channel | **Protected** |
| `Chat.ReadWrite.All` *(or RSC)* | `send_chat_message` | Proactive 1:1 message | High |
| `Files.Read.All` + `Sites.Read.All` | `get_channel_files_folder`, `list_children`, `resolve_share_url`, `get_drive_item_content` | SharePoint / Forms-responses ingestion | High |
| `Mail.Send` | `send_mail` | Post-event feedback emails | High (broad — sends as any user; consider scoping) |

**Two ways to grant the channel/chat permissions:**
- **RSC (Resource-Specific Consent)** — declared in the manifest under `authorization.permissions.resourceSpecific`, consented by the **team owner** at install time, scoped to *only the teams the app is installed in*. Lowest blast radius. Preferred for `ChannelMessage.Read.Group` / `ChannelMessage.Send.Group`.
- **Tenant-wide application permissions** — broader, require **Global Admin consent**, and some (channel read/send as app) are **"protected APIs"** that need a request to Microsoft. Use only where RSC can't cover it.

**Guidance:** start with the **minimum** that unblocks testing. For a first pilot you may only need the bot registration (no Graph at all) to test the conversational agent in DMs. Add Graph permissions feature-by-feature. Because EventBuddy **degrades gracefully** (no Graph creds → create-event persists locally only, etc.), you don't have to grant everything up front.

> Note on `send_mail`: `/me/sendMail` requires *delegated* context; with an **application** token you must use `/users/{id}/sendMail`. There's already a `⚠ verify SDK` comment on that method — confirm the path before relying on mail in production.

---

## 6. The integration runbook (step by step)

### Phase A — Entra app (IT)
1. IT → **Entra admin center → App registrations → New registration**.
   - Name: `EventBuddy`.
   - Supported account types: **Single tenant** (Accounts in this organizational directory only) — recommended for an internal bot.
2. Copy the **Application (client) ID** and **Directory (tenant) ID** → these become `MICROSOFT_APP_ID` and `MICROSOFT_APP_TENANT_ID`.
3. **Certificates & secrets → New client secret** → copy the value → `MICROSOFT_APP_PASSWORD`. (Note the expiry; rotate before it lapses.)
4. If using one app for Graph too: **API permissions → add the §5 permissions → Grant admin consent**.

### Phase B — Azure Bot resource (IT or you)
5. Azure portal → create an **Azure Bot** resource.
   - **Type of app:** Single-tenant.
   - **App ID:** the one from step 2 ("Use existing app registration").
6. **Configuration → Messaging endpoint:** `https://<your-agentbase-endpoint>/api/messages`.
7. **Channels → Microsoft Teams → enable → Save.**

### Phase C — Teams app package (you)
8. Author `manifest.json` (see §7), add a 192×192 color icon and a 32×32 outline icon, zip the three files together (icons at the zip root, not in a subfolder).

### Phase D — Deploy creds (you)
9. On AgentBase, set `MICROSOFT_APP_ID`, `MICROSOFT_APP_PASSWORD`, `MICROSOFT_APP_TENANT_ID` (and `GRAPH_*`, `MICROSOFT_TEAM_ID` when you add Graph features), then `make deploy`.
10. `make health` / `make endpoint` to confirm the public endpoint is live and matches step 6.

### Phase E — Test (you + IT)
11. IT enables **custom app upload** for your account or a test team (see §8).
12. You **upload the app to a single test team** and exercise it. Iterate.

### Phase F — Rollout (IT)
13. When ready, IT publishes the app **org-wide** via Teams Admin Center, optionally gated by an **app permission/setup policy** to a pilot group first.

---

## 7. The Teams manifest — the fields that matter

A minimal-but-correct `manifest.json` (schema `v1.17`+). Replace the GUIDs/domain.

```jsonc
{
  "$schema": "https://developer.microsoft.com/en-us/json-schemas/teams/v1.17/MicrosoftTeams.schema.json",
  "manifestVersion": "1.17",
  "id": "<ENTRA_APP_ID>",                 // the bot's Entra App ID
  "version": "1.0.0",
  "developer": { "name": "...", "websiteUrl": "...", "privacyUrl": "...", "termsOfUseUrl": "..." },
  "name": { "short": "EventBuddy", "full": "EventBuddy" },
  "description": { "short": "...", "full": "..." },
  "icons": { "color": "color.png", "outline": "outline.png" },
  "accentColor": "#0F4880",
  "bots": [
    {
      "botId": "<ENTRA_APP_ID>",
      "scopes": ["personal", "team"],     // + "groupChat" if you want it
      "supportsFiles": false,
      "isNotificationOnly": false,
      "commandLists": [ /* optional: surface example commands */ ]
    }
  ],
  "permissions": ["identity", "messageTeamMembers"],
  "validDomains": ["<your-agentbase-endpoint-host>"],
  // OPTIONAL — only if you add SSO later:
  // "webApplicationInfo": { "id": "<ENTRA_APP_ID>", "resource": "api://<host>/<ENTRA_APP_ID>" },
  // OPTIONAL — RSC, consented by team owner at install (preferred over tenant-wide for channel read/send):
  "authorization": {
    "permissions": {
      "resourceSpecific": [
        { "name": "ChannelMessage.Read.Group", "type": "Application" }
        // add "ChannelMessage.Send.Group" etc. as features require
      ]
    }
  }
}
```

You can author and validate this visually in the **Teams Developer Portal** (dev.teams.microsoft.com) instead of hand-editing — it also packages the zip for you.

---

## 8. Testing strategy — and "is it OK to test in the real corporate Teams?"

You raised two real concerns: (a) you can't test in Teams without permission, and (b) is testing in the *real* corporate Teams acceptable. Here's the layered answer.

### Tier 1 — No Teams at all (do this now, today) ✅
You already have the **Bot Framework Emulator** path documented ([EventBuddy-Emulator-Testing-Guide.md](EventBuddy-Emulator-Testing-Guide.md)) and the **dev route** `POST /api/dev/handle` (mounted when `DEV_ROUTES_ENABLED=true`). These exercise the *entire* agent — routing, tools, memory, HITL cards — with **zero Teams dependency and zero permissions**. Everything that doesn't strictly require a Teams/Graph round-trip can be fully validated here. **This is the bulk of your testing and needs nothing from IT.**

What you *can't* test here: real Teams activity shapes (channel_data, team ids), real Graph calls (channel create, message read, files), proactive delivery, and Adaptive Card rendering in the actual client.

### Tier 2 — Real Teams, scoped to a test team (the safe "real" test) ✅
**Yes, testing in the real corporate Teams is fine — when scoped correctly.** A Teams bot only ever sees:
- messages in chats/channels **it is explicitly added to**, and
- (for Graph) only the resources its **granted permissions / RSC consent** allow.

So the safe pattern is:
1. IT enables **custom app upload (sideloading)** — either org-wide default policy, or (better) a **dedicated app setup policy assigned only to your account** so the rest of the org is unaffected. (Setting can take up to 24h to propagate.)
2. You create or get a **dedicated test team** ("EventBuddy Sandbox") with a few volunteer members.
3. You **upload the app to that team only**. The bot is invisible to everyone else.
4. If you use RSC, the **team owner consents** at install — scoped to *that team only*.

This contains blast radius completely: the bot can't read or post anywhere it isn't installed, and grants are per-team. This is the standard, IT-friendly way to pilot a Teams bot in a production tenant.

### Tier 3 — Org-wide publish 🚦
Only after Tier 2 passes. IT publishes via Teams Admin Center, ideally behind a **permission policy** that limits availability to a pilot group before full rollout.

### What to ask IT for, testing-wise
- Enable **custom app upload** for **your account** (scoped policy preferred over org-wide).
- A **test team** you own (or owner rights on one), so you can consent to RSC and add/remove the bot freely.
- Confirmation of whether they'll grant the Graph permissions now or stage them (you can test DM conversation flows *before* any Graph consent).

---

## 9. Risk, security & graceful-degradation notes

- **Single-tenant** the Entra app — there's no reason an internal bot should accept other tenants.
- **Turn on real auth before any non-emulator use.** Empty `MICROSOFT_APP_*` = the adapter accepts unauthenticated activities. Fill the creds (Phase D) before sideloading.
- **Secret hygiene:** the client secret lives only in AgentBase env / your secrets store, never in git. Note its expiry and rotate.
- **Least privilege:** grant Graph permissions feature-by-feature; prefer **RSC** (team-scoped, owner-consented) over tenant-wide app permissions; the protected channel-read/send APIs may require a Microsoft request — don't block the pilot on them.
- **`Mail.Send` is broad** — it can send as any mailbox. Scope it (application access policy) or defer it until needed.
- **Graceful degradation is load-bearing** (CLAUDE.md): no Graph creds → create-event persists locally only; no MaaS → regex router; no Redis → in-memory memory. This is *why* you can integrate incrementally — each missing grant degrades a feature instead of breaking the bot. Preserve this.
- **Data residency / compliance:** EventBuddy stores transcripts and summaries in Supabase Postgres and Redis, reached over public TLS. Flag this to IT — corporate data (channel messages, member info) will transit/rest outside the Microsoft tenant. They may have a policy on that.

---

## 10. Ready-to-send request for IT

> **Subject: EventBuddy Teams bot — Entra/Bot registration request**
>
> Hi team, I'd like to integrate an internal Teams bot ("EventBuddy") for event-lifecycle management. Requesting the following:
>
> 1. **Entra app registration** named `EventBuddy`, **single-tenant**. Please share the **Application (client) ID** and **Directory (tenant) ID**, and create a **client secret** (share via [secure channel]).
> 2. **Azure Bot resource** bound to that App ID, with:
>    - **Messaging endpoint:** `https://<AGENTBASE_ENDPOINT>/api/messages`
>    - **Microsoft Teams channel enabled**
>    (If you'd prefer I create the Azure Bot resource, please grant me Contributor on a subscription/resource group.)
> 3. **Custom app upload (sideloading) enabled for my account** (a scoped app-setup policy is fine — doesn't need to be org-wide), and a **test team I own** so I can pilot safely in isolation.
> 4. **Microsoft Graph application permissions** (admin consent) — I'd like to **stage these**; for the first pilot **none are required** (the conversational bot works in DMs without Graph). When we enable channel/files/mail features I'll need, in order of need:
>    - `Channel.Create.All` (or `Group.ReadWrite.All`) — create event channels
>    - `ChannelMessage.Read.Group` / `ChannelMessage.Send.Group` via **RSC** (team-owner consent, preferred) — read/post in channels
>    - `Files.Read.All` + `Sites.Read.All` — read SharePoint/Forms files
>    - `Chat.ReadWrite.All`, `Mail.Send` — proactive DM / feedback email
>
> **Scope** (install): `personal` + `team`. **Endpoint, name, scope, permissions** as above. Happy to walk through any of it.
>
> Note: the service stores conversation data in a cloud Postgres/Redis reached over TLS — flagging in case there's a data-handling policy to review.

---

## Appendix — config keys this unlocks

| `.env` key | Source | When |
|---|---|---|
| `MICROSOFT_APP_ID` | Entra app → Application (client) ID | Phase A |
| `MICROSOFT_APP_PASSWORD` | Entra app → client secret | Phase A |
| `MICROSOFT_APP_TENANT_ID` | Entra → Directory (tenant) ID | Phase A |
| `MICROSOFT_TEAM_ID` | the team you create channels under (test team during pilot) | Phase E |
| `GRAPH_TENANT_ID` / `GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET` | same app (or a separate Graph app) | when adding Graph features |

**References:**
- [Connect a Bot Framework bot to Microsoft Teams](https://learn.microsoft.com/en-us/azure/bot-service/channel-connect-teams?view=azure-bot-service-4.0)
- [Configure app in Microsoft Entra ID (bot SSO)](https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/authentication/bot-sso-register-aad)
- [Manage custom app policies and settings (sideloading)](https://learn.microsoft.com/en-us/microsoftteams/teams-custom-app-policies-and-settings)
- [Azure Bot channels registration](https://github.com/MicrosoftDocs/msteams-docs/blob/main/msteams-platform/includes/bots/azure-bot-channels-registration.md)
</content>
</invoke>
