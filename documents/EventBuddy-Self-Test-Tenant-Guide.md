# EventBuddy — Self-Testing in Your Own Microsoft 365 Tenant

**Goal:** stand up a personal Microsoft 365 + Azure environment where **you are the admin**, and run EventBuddy end-to-end **before** asking corporate IT for anything. This is a full dress rehearsal of [EventBuddy-IT-Onboarding-Request.md](EventBuddy-IT-Onboarding-Request.md) — every step IT would do, you do yourself.

**Time:** ~2–3 hours of active work (plus up to 24h waiting for custom-app-upload to propagate).
**Cost:** free (M365 Developer sandbox + Azure free tier + Bot F0 SKU).

---

## 0. What you're building

```
  Your AgentBase runtime (already live, tenant-agnostic)
        https://endpoint-0a09ccce-...vngcloud.vn/api/messages
                          ▲
                          │  Bot Framework handshake
                          │
   ┌──────────────────────┴───────────────────────┐
   │  AZURE (free account)                          │
   │   • Azure Bot resource (F0) → Teams channel    │
   └──────────────────────┬───────────────────────┘
                          │ uses App ID + secret from ↓
   ┌──────────────────────┴───────────────────────┐
   │  M365 DEV TENANT (you are Global Admin)        │
   │   • Entra app registration (identity)          │
   │   • Graph permissions + admin consent          │
   │   • Teams: sideload app, test team, mailboxes  │
   └────────────────────────────────────────────────┘
```

Two free accounts, **same admin identity**, pointed at your **existing** endpoint. Nothing about the bot's code or endpoint changes — only the credentials it authenticates with.

---

## 1. Get a Microsoft 365 Developer tenant (your identity + Teams + Graph)

1. Go to **https://developer.microsoft.com/microsoft-365/dev-program** and **Join**.
   - Sign in with any Microsoft account (personal is fine).
   - Microsoft has tightened eligibility — you may need an active **Visual Studio subscription** or to complete a qualifying activity. If you can't get in, skip to the **Fallback** box below.
2. Choose **"Instant sandbox"** when offered — it pre-provisions ~16 fake users with mailboxes, Teams, and sample data. (The "configurable sandbox" is empty; the instant one saves you hours and gives `User.Read.All` / `TeamMember.Read.All` real data to hit.)
3. You'll get a tenant like `yourname.onmicrosoft.com` and an admin login `admin@yourname.onmicrosoft.com`. **Save the password** — this is your Global Admin.
4. The sandbox is **E5, free, 90 days, auto-renewing** as long as you keep using it.

> **Fallback — Business Standard trial.** If the Developer Program rejects you: go to **https://www.microsoft.com/microsoft-365/business** → Business Standard → **Try free for 1 month**. You get a full tenant with ~25 licenses for 30 days. Works identically for testing; just shorter-lived, has no pre-seeded sample users, and will ask for a card (set a calendar reminder to cancel). Everything below applies the same way.

**Checkpoint:** you can sign into `https://admin.microsoft.com` as the tenant admin.

---

## 2. Get a free Azure account (the Bot resource lives here, not in M365)

The Azure Bot resource — the thing that ties your endpoint to the Teams channel — is an **Azure** resource, separate from M365.

1. Go to **https://azure.microsoft.com/free** → **Start free**.
2. **Critical:** sign in with your **new tenant admin** (`admin@yourname.onmicrosoft.com`), *not* a different Microsoft account. This keeps the Azure subscription and the M365 tenant in the **same directory**, so your single-tenant bot's identity lines up. Mismatched tenants = auth pain.
3. You get $200 credit for 30 days + always-free services. The **Azure Bot F0 SKU is free indefinitely**, so cost isn't a concern even after the credit lapses.

**Checkpoint:** you can open `https://portal.azure.com` and see a subscription under your tenant.

---

## 3. Create the Entra app registration (the bot's identity)

In `https://entra.microsoft.com` (or Azure portal → Microsoft Entra ID):

1. **App registrations → New registration.**
   - **Name:** `EventBuddy`
   - **Supported account types:** **Accounts in this organizational directory only (single tenant).**
   - Leave redirect URI empty. **Register.**
2. From the **Overview** page, copy:
   - **Application (client) ID** → this is your `MICROSOFT_APP_ID` and `GRAPH_CLIENT_ID`.
   - **Directory (tenant) ID** → your `MICROSOFT_APP_TENANT_ID` and `GRAPH_TENANT_ID`.
3. **Certificates & secrets → New client secret.**
   - Description `eventbuddy-dev`, expiry 90 days.
   - **Copy the secret VALUE immediately** (not the Secret ID) → `MICROSOFT_APP_PASSWORD` and `GRAPH_CLIENT_SECRET`. It's shown only once.

> EventBuddy uses one app registration for both the Bot identity and Graph (client-credentials). That's fine for the sandbox. In production IT may split them (see §5 of the onboarding request) — your config already supports separate `MICROSOFT_APP_*` and `GRAPH_*` values if so.

**Checkpoint:** you have client ID, tenant ID, and secret value saved.

---

## 4. Create the Azure Bot resource and enable the Teams channel

In `https://portal.azure.com`:

1. **Create a resource → search "Azure Bot" → Create.**
   - **Bot handle:** `EventBuddy` (must be globally unique — add a suffix if taken).
   - **Subscription / Resource group:** create a new RG `eventbuddy-rg`.
   - **Pricing tier:** **F0 (Free).**
   - **Microsoft App ID:** choose **Use existing app registration** → paste the **client ID** from §3.
   - **App type:** **Single Tenant.** Enter your **tenant ID**.
   - **Create.**
2. Once deployed, open the bot resource → **Settings → Configuration.**
   - **Messaging endpoint:**
     ```
     https://endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn/api/messages
     ```
   - **Apply.**
3. **Settings → Channels → Microsoft Teams → Apply/Agree → Save.** The Teams icon should show as running.

**Checkpoint:** the bot's Channels page lists **Microsoft Teams** as enabled, and the messaging endpoint is set to your live URL.

> **Optional sanity test — Web Chat.** Before touching Teams, click **Test in Web Chat** on the bot resource. If your endpoint and creds are right, you'll get a reply. (If it errors, it's almost always the secret or endpoint — fix here before moving on.)

---

## 5. Add Graph permissions and grant admin consent

Back in **Entra → App registrations → EventBuddy → API permissions:**

1. **Add a permission → Microsoft Graph → Application permissions.** Add the full §4 set from the onboarding request:
   - `Channel.Create.All` (or `Group.ReadWrite.All`)
   - `Files.Read.All`
   - `Sites.Read.All`
   - `User.Read.All`
   - `TeamMember.Read.All`
   - `Mail.Send`
2. **Grant admin consent for <your tenant>** (the button at the top). You're the admin, so this is one click. All rows should flip to **Granted ✓**.

> `ChannelMessage.Read.Group` is **RSC** — you do *not* add it here. It's declared in the manifest and consented by the team owner (you) at install time in §7.

**Checkpoint:** every application permission shows a green "Granted for <tenant>".

---

## 6. Enable custom app upload (sideloading) in Teams

In **https://admin.teams.microsoft.com** (Teams admin center):

1. **Teams apps → Setup policies → Global (Org-wide default)** (or make a new policy and assign it to your admin user).
2. Turn **Upload custom apps** → **On. Save.**

> ⏳ This can take **up to 24 hours** to propagate. Do this step early. You can keep working on config (§9) while it settles. If the "Upload a custom app" option doesn't appear in Teams yet, this is why — wait it out.

**Checkpoint:** in the Teams client, **Apps → Manage your apps → Upload an app → Upload a custom app** is visible.

---

## 7. Provision a sender mailbox for `Mail.Send`

Application `Mail.Send` sends *as an existing mailbox* — it doesn't invent one.

1. In **https://admin.microsoft.com → Users → Active users**, either use an existing seeded user (e.g. `AdeleV@yourname.onmicrosoft.com`) or **Add a shared mailbox** named `eventbuddy@yourname.onmicrosoft.com`.
2. Note the address → this is your `GRAPH_SENDER_UPN`.
3. *(Optional, mirrors production)* Scope `Mail.Send` to just that mailbox with an **Application Access Policy** via Exchange Online PowerShell:
   ```powershell
   New-ApplicationAccessPolicy -AppId <client-id> `
     -PolicyScopeGroupId eventbuddy@yourname.onmicrosoft.com `
     -AccessRight RestrictAccess -Description "EventBuddy send-as only"
   ```
   Skip this if you just want it working fast — it's a tightener, not a requirement.

**Checkpoint:** you have a mailbox address the bot will send as.

---

## 8. Create a test team

In the Teams client (signed in as your admin or a seeded user):

1. **Teams → + → Create team → From scratch → Private.** Name it `EventBuddy Sandbox`.
2. Add a couple of the seeded sample users as members so roster/membership tests have data.
3. Note: EventBuddy keys channel Graph calls off the **team's group id**. After creating, you'll grab it in §9 (or let the bot resolve it).

**Checkpoint:** a private team you own, with a few members.

---

## 9. Point EventBuddy's config at your sandbox

Edit your runtime `.env` (the AgentBase deployment config) with the values you collected. Mapping:

| Config key | Source |
|---|---|
| `MICROSOFT_APP_ID` | §3 client ID |
| `MICROSOFT_APP_PASSWORD` | §3 secret value |
| `MICROSOFT_APP_TENANT_ID` | §3 tenant ID |
| `MICROSOFT_TEAM_ID` | §8 team's group id (Teams → team → ⋯ → Get link to team, or via Graph) |
| `GRAPH_TENANT_ID` | §3 tenant ID |
| `GRAPH_CLIENT_ID` | §3 client ID |
| `GRAPH_CLIENT_SECRET` | §3 secret value |
| `GRAPH_SENDER_UPN` | §7 mailbox address |

Leave `AGENT_MODE=llm` and your MaaS creds as-is. Then **redeploy** the runtime (`make deploy`) so the new creds take effect.

> The bot is **single-tenant**: these sandbox creds authenticate only against your sandbox tenant. When you later move to the corporate tenant, you swap this whole block for IT's values and redeploy — the **endpoint and code don't change.**

**Checkpoint:** `make deploy` succeeds and `make health` is green with the new creds.

---

## 10. Sideload and install the app

1. If `teams-app/eventbuddy.zip` doesn't already have your real App ID baked in, rebuild it:
   - Edit [teams-app/manifest.json](../teams-app/manifest.json): replace both `REPLACE_WITH_ENTRA_APP_ID` placeholders (the top-level `id` **and** `bots[0].botId`) with your **§3 client ID**.
   - Run `teams-app/build.sh` to repackage the zip.
2. In Teams: **Apps → Manage your apps → Upload an app → Upload a custom app** → pick `eventbuddy.zip`.
3. **Add to the `EventBuddy Sandbox` team.** At install, Teams shows the **RSC consent** prompt for `ChannelMessage.Read.Group` — accept as team owner.

**Checkpoint:** EventBuddy appears in the team and you can @mention it / DM it.

---

## 11. Run the end-to-end test pass

Exercise each capability and confirm the Graph wiring works:

- [ ] **Chat reply** — DM the bot; confirm the LLM agent responds (no Graph needed).
- [ ] **Channel reply / proactive post** — @mention in a channel; confirm it replies in-channel.
- [ ] **Create channel** — ask it to create an event channel (`Channel.Create.All`).
- [ ] **Read channel files** — drop a file in the channel's Files tab, ask the bot about it (`Files.Read.All` + `Sites.Read.All`).
- [ ] **Member lookup** — ask for a member's info (`User.Read.All` / `TeamMember.Read.All`).
- [ ] **Read channel discussion** — ask it to summarize the channel (`ChannelMessage.Read.Group` RSC).
- [ ] **Send email** — trigger a notification/feedback email to a seeded user (`Mail.Send` as `GRAPH_SENDER_UPN`); check that user's inbox.

If any step 4xx's, the bot's debug footer (`AGENT_DEBUG=true`) lists the failing tool call + exception — match it to the permission/config above.

---

## 12. When the sandbox passes → hand off to corporate IT

You've now proven the whole flow. To go corporate:

1. Send [EventBuddy-IT-Onboarding-Request.md](EventBuddy-IT-Onboarding-Request.md) (or the VI version) to IT — you can now answer every question in it from experience.
2. When IT returns the corporate **App ID / tenant ID / secret / sender mailbox**, swap the §9 config block and redeploy.
3. Re-run the §11 checklist in the corporate test team.

---

## Quick reference — what changes between tenants

| | Sandbox | Corporate |
|---|---|---|
| Messaging endpoint | **same** | **same** |
| Bot code / manifest structure | **same** | **same** (new App ID baked in) |
| `MICROSOFT_APP_*`, `GRAPH_*` | your sandbox values | IT's values |
| `GRAPH_SENDER_UPN` | sandbox mailbox | corporate mailbox |
| Admin consent | you click it | IT clicks it |
| Custom app upload | you enable it | IT enables it (scoped) |

The only thing that ever moves between environments is **credentials + the sender mailbox**. Everything else is portable — which is exactly why this rehearsal de-risks the real rollout.

---

*Companion documents: [EventBuddy-IT-Onboarding-Request.md](EventBuddy-IT-Onboarding-Request.md) (the send-to-IT request), [EventBuddy-Teams-Integration-Guide.md](EventBuddy-Teams-Integration-Guide.md) (full architecture & runbook), and the app package in [`teams-app/`](../teams-app/).*
