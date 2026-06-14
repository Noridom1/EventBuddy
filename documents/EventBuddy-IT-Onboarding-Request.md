# EventBuddy — Teams Onboarding Request for IT (Entra Admin)

**To:** IT / Microsoft Entra administrator
**From:** EventBuddy developer team
**Date:** 2026-06-14
**Purpose:** register an internal Microsoft Teams bot ("EventBuddy") in our tenant so it can be piloted safely.

This is a self-contained request. The four items you asked for — **name, endpoint, scope, permissions** — are in §1. What we need *you* to do is in §2; what we need *back* is in §3.

---

## 1. The four details you asked for

| Item | Value |
|---|---|
| **App / bot name** | `EventBuddy` |
| **Messaging endpoint** | `https://endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn/api/messages` |
| **Endpoint host (for validDomains)** | `endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn` |
| **Install scope** | `personal` (1:1 chat) + `team` (channel) |
| **Account type** | **Single-tenant** (this organization only) |
| **Graph permissions** | **Full set requested up front** to enable end-to-end testing — see §4. |

The endpoint is already live (public HTTPS, AgentBase runtime). You can sanity-check it returns a response at the host root before wiring.

---

## 2. What we're asking you to do

### 2.1 Create the Entra app registration (required)
- **Entra admin center → App registrations → New registration**
- Name: `EventBuddy`
- Supported account types: **Single tenant** (Accounts in this organizational directory only)
- After creation: **Certificates & secrets → New client secret** (note the expiry).

### 2.2 Create the Azure Bot resource (required)
- Azure portal → create an **Azure Bot** resource.
- App type: **Single-tenant**; **use the existing app registration** from 2.1 (paste its App ID).
- **Configuration → Messaging endpoint:** the URL in §1.
- **Channels → Microsoft Teams → enable → Save.**

> If you'd rather *we* create the Azure Bot resource, please instead grant us **Contributor** on a subscription or resource group, and we'll do 2.2 ourselves.

### 2.3 Enable custom app upload for our test account (required for piloting)
- **Teams admin center → Teams apps → Setup policies.**
- Either set the **Global (Org-wide default)** "Upload custom apps" to **On**, **or** (preferred — lower blast radius) create a **new app setup policy** with "Upload custom apps" = On and assign it **only to our developer account(s)**.
- Note: this can take **up to 24 hours** to propagate.

### 2.4 Give us (or confirm) a test team
- A **dedicated test team we own** ("EventBuddy Sandbox") with a few volunteer members, so we can install/remove the bot freely and consent to team-scoped permissions in isolation. Org-wide visibility is **not** wanted yet.

### 2.5 Add and admin-consent the Microsoft Graph application permissions in §4 (required for full testing)
- On the EventBuddy app registration: **API permissions → Add a permission → Microsoft Graph → Application permissions** → add the permissions listed in §4 → **Grant admin consent**.
- For the channel-message **read** capability, the team owner consents to the **RSC** permission at install time (it's declared in our manifest) — no tenant-wide grant needed for that one.

### 2.6 Provide a sender mailbox for outbound email (required if testing the email feature)
- The bot sends email *as a real mailbox* (application `Mail.Send` does not invent one). Please **provision or nominate a mailbox** for it — e.g. a shared mailbox `eventbuddy@vng.com.vn` — and share its address.
- Recommended: bind an **Application Access Policy** so the EventBuddy app can send **only** from that mailbox (not from arbitrary users). We'll configure the bot to send as exactly this address.

---

## 3. What we need back from you

1. **Application (client) ID** of the EventBuddy app registration.
2. **Directory (tenant) ID**.
3. The **client secret value** — please send via a secure channel (not plain email).
4. Confirmation that the **Teams channel is enabled** on the Azure Bot resource.
5. Confirmation that **custom app upload** is enabled for our account (and the **test team** name / that we have owner rights).
6. The **sender mailbox address** (§2.6) the bot may send email as.

We plug 1–3 into the bot's runtime configuration. For full end-to-end testing we also need the Graph permissions in §4 added and admin-consented (§2.5).

---

## 4. Microsoft Graph permissions — full set for end-to-end testing

We want to validate the **complete** system (create channels, read channel files, look up members, send email, read channel discussion), so we're requesting the full set up front. The bot's **chat replies still need no Graph permissions** — everything below powers a specific capability:

| Capability we're testing | Permission | Type / how granted | Notes |
|---|---|---|---|
| Create an event's Teams channel | `Channel.Create.All` | Application — admin consent | Or `Group.ReadWrite.All` if your policy prefers the group-level grant |
| Read & download channel files (SharePoint) | `Files.Read.All` + `Sites.Read.All` | Application — admin consent | Broad. Can be tightened to **`Sites.Selected`** scoped to the test team's site — see §5 |
| Look up member profiles (name, email, id) | `User.Read.All` | Application — admin consent | Resolves roster emails → user records |
| Read team roster / membership | `TeamMember.Read.All` | Application — admin consent | Who's in the team/event |
| Send notification / feedback email | `Mail.Send` | Application — admin consent | Broad (can send as any mailbox). Please scope with an **Application Access Policy** limited to the EventBuddy mailbox — see §5 |
| Read channel discussion | `ChannelMessage.Read.Group` | **RSC** — team-owner consent at install | Already in our manifest. **Preferred over** the tenant-wide `ChannelMessage.Read.All`, which is a Microsoft **"protected API"** requiring a separate approval request |

**Posting messages into a channel/chat** is handled **without an extra Graph permission**: the bot posts **proactively through the Bot Framework connector** once it's installed in the team/chat. (Sending a channel message *as the app via Graph* is itself a protected API, so we deliberately avoid that path.)

> Net effect: the only items that need **tenant-wide admin consent** are `Channel.Create.All`, `Files.Read.All`, `Sites.Read.All`, `User.Read.All`, `TeamMember.Read.All`, `Mail.Send`. Channel read uses **RSC** (no tenant grant); channel/chat sending uses the **Bot Framework** (no Graph grant).

---

## 5. Data-handling note (please review)

EventBuddy stores conversation transcripts and rolling summaries in a **cloud Postgres (Supabase) and Redis**, reached over public TLS. This means some corporate conversation data (channel messages it's asked to summarize, event/member info) will **transit and rest outside the Microsoft 365 tenant**. Flagging so it can be checked against any data-residency or DLP policy before wider rollout. Happy to discuss controls (region, retention, encryption) if needed.

**Scoping the broad permissions (recommended).** Because the §4 application permissions are tenant-wide, we're happy to apply these tighteners for the test phase:
- **`Sites.Selected`** instead of `Files.Read.All` + `Sites.Read.All` — grants file access only to the **test team's SharePoint site** you nominate, nothing else.
- An **Application Access Policy** on `Mail.Send` — restricts the bot to sending only from a designated **EventBuddy mailbox**, not arbitrary users.
- A **short secret expiry** (e.g. 90 days) and a **separate app registration for Graph** vs the bot identity, if you prefer to isolate the high-privilege consent.

---

## 6. Why scoped testing in production Teams is safe

A Teams bot only ever sees:
- chats/channels **it has been explicitly added to**, and
- (for Graph) only the data its **granted permissions / RSC consent** allow.

By enabling upload only for our account (§2.3) and installing only into a **test team we own** (§2.4), the bot is **invisible to the rest of the organization** and its *messaging* (replies, proactive posts) is confined to where it's installed. RSC consent is per-team. We will request org-wide publishing (Teams Admin Center, behind a pilot policy) only **after** the sandbox test passes.

**One honest caveat:** the tenant-wide **application** Graph permissions in §4 (`Files`/`Sites`/`User`/`TeamMember`/`Mail.Send`) are *not* limited to the test team — the bot's credentials could technically read those resources tenant-wide. The §5 tighteners (`Sites.Selected`, mail Application Access Policy, isolated Graph app, short secret) bring that back down to the test scope. We're glad to apply whichever of those you require.

---

*Companion documents (developer side): [EventBuddy-Teams-Integration-Guide.md](EventBuddy-Teams-Integration-Guide.md) (full architecture & runbook) and the app package in [`teams-app/`](../teams-app/) (manifest + build).*
