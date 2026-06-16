# EventBuddy — Setup & User Guide

🌐 **English** · [Tiếng Việt](Teams-Setup-Guide.vi.md)

> How to install EventBuddy in Microsoft Teams, sign in, and start using it.
> No technical knowledge needed for the main steps.

**Live page (get the app here):**
👉 https://endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn/

**Companion docs:** [System Architecture](System-Architecture.md) · [README](../README.md)

---

## Get started in 3 steps

### Step 1 — Install the app

1. Open the **[EventBuddy page](https://endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn/)** and click **Download** to save `eventbuddy.zip`.
2. In **Microsoft Teams**, go to the left sidebar → **Apps**.
3. Click **Manage your apps** (bottom) → **Upload an app** → **Upload a custom app**.
4. Select the **`eventbuddy.zip`** you just downloaded.
5. When Teams asks where to add it, choose **Add** (for a personal 1-1 chat — the easiest place to
   start). You can also add it to a **group chat** or a **team channel** later.

EventBuddy now opens in a chat, like any teammate.

> 💡 Don't see **"Upload a custom app"**? Your organization may need to turn on custom-app upload
> for your account — ask your IT/Teams admin (see [the admin section](#for-it-admins-one-time-setup)).

### Step 2 — Sign in

The first time you use EventBuddy, connect it to your Microsoft 365 account so it can act on your
behalf (read files, send reminders, create channels).

1. In the chat, simply type:

   ```
   sign in
   ```

2. EventBuddy replies with a **Sign in** button. Click it.
3. A Microsoft sign-in window opens — choose your work account and approve the access.
4. Teams confirms you're connected. That's it — you're ready.

> You only need to do this once. If you ever want to reconnect with a different account or refresh
> permissions, type **`sign out`** and then **`sign in`** again.
>
> EventBuddy will also pop up the **Sign in** button on its own the first time it needs access it
> doesn't have yet — just click it and ask again.

### Step 3 — Start talking

Just tell EventBuddy what you want in plain language. Try:

- *"Create an event called Demo Day with thoptk and phucnlt2."*
- *"What are my tasks?"*
- *"Add a task to book the venue, due June 25."*

That's the whole setup. The rest of this page shows **what you can ask** and, at the end, the
**one-time admin steps** if EventBuddy hasn't been set up in your organization yet.

---

## What you can ask EventBuddy

EventBuddy understands natural language — you don't need exact commands. It behaves slightly
differently depending on where you've added it.

### In a 1-1 chat (just you)
You're in charge here. Good things to say:
- *"Create an event called Spring Hackathon with \<your teammates\>."*
- *"What events am I part of?"* → then *"Focus on Spring Hackathon."*
- *"What are my tasks?"* / *"Add a task to send invitations, assign it to me, due Friday."*
- *"Write the post-event report."*

### In a group chat (your organizing team)
Everyone in the chat is an equal partner — anyone can ask EventBuddy to do anything.
- *"This group is for the Spring Hackathon — help us organize."* (sets up the event)
- *"Add the new people in this chat to the event."*
- *"Read participants.csv and remind everyone who hasn't registered yet."*

### In a team channel
The channel becomes the event's shared workspace. EventBuddy follows the discussion, so you can ask:
- *"Summarize what we've discussed."*
- *"Generate the report for this event."*

### A few handy examples
| You say… | EventBuddy does… |
|---|---|
| *"Remind everyone about the deadline tomorrow."* | Drafts reminders and shows a confirmation card before sending. |
| *"Email the team the agenda."* | Composes the email; you approve before it goes out. |
| *"Read the budget file and tell me the total."* | Opens the shared file (Excel, Word, PDF, image…) and answers. |
| *"Add a task to print badges, assign it to Lan, due June 20."* | Adds it to the event's task board. |

> 🔒 **Nothing is sent without your OK.** Every email, message, or reminder shows a **confirmation
> card** first — you see exactly who gets what and click to send.

---

## Troubleshooting

| Problem | Try this |
|---|---|
| **"Upload a custom app" is missing** | Your admin needs to enable custom-app upload for your account — see below. |
| **EventBuddy says it needs access** | Type **`sign in`** and click the button, then ask again. |
| **It's acting on the wrong account** | Type **`sign out`**, then **`sign in`** and pick the right account. |
| **A file/channel action says it's unavailable** | That feature needs a permission your admin hasn't granted yet — see below. EventBuddy still works for everything else. |

---

## For IT admins (one-time setup)

> Skip this entirely if EventBuddy is already available in your organization — end users only need
> the 3 steps above. This section is for the admin enabling it the first time.

EventBuddy is already built and hosted; you only need to register its identity in your Microsoft
tenant and allow it to be installed.

**1. Register the bot identity (Microsoft Entra)**
- Entra admin center → **App registrations → New registration** → name `EventBuddy`,
  **single tenant**. Note the **Application (client) ID** and **Directory (tenant) ID**.
- **Certificates & secrets → New client secret** → save the value.

**2. Create the Azure Bot resource**
- Azure portal → create an **Azure Bot** → "Use existing app registration" (the ID above).
- **Messaging endpoint:**
  `https://endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn/api/messages`
- **Channels → Microsoft Teams → enable.**

**3. Allow installation**
- Enable **custom app upload (sideloading)** for the pilot users (a scoped app-setup policy is
  preferred over an org-wide change). Can take up to 24h to propagate.

**4. Grant Microsoft 365 access — staged**
EventBuddy uses **delegated** Microsoft Graph access: each user signs in (the "sign in" step above)
and acts as themselves, so the bot only does what that person could already do. The conversational
features need no extra admin consent. As you enable richer features, grant these and **admin-consent**
the matching delegated permissions:

| Feature | Delegated Graph permission |
|---|---|
| Read/send channel messages, create event channels | `Channel.Create.All`, `ChannelMessage.Read.All`, `ChannelMessage.Send` |
| Read SharePoint/OneDrive/Forms files | `Files.Read.All`, `Sites.Read.All` |
| Send 1-1 messages / feedback email | `Chat.ReadWrite`, `Mail.Send` |

Because EventBuddy **degrades gracefully**, you can grant these one at a time — a missing permission
disables one feature instead of breaking the bot.

**5. Publish (optional)**
When the pilot looks good, publish org-wide via the Teams Admin Center, ideally behind a permission
policy that targets a pilot group first.

### Admin quick reference

| Item | Value |
|---|---|
| Landing page | `https://endpoint-0a09ccce-2059-4ce4-b1b7-8a35d674aa0c.agentbase-runtime.aiplatform.vngcloud.vn/` |
| App package | `…/download/eventbuddy.zip` |
| Messaging endpoint | `…/api/messages` |
| Install scopes | `personal`, `team`, `groupChat` |

**Microsoft references:**
[Connect a bot to Teams](https://learn.microsoft.com/en-us/azure/bot-service/channel-connect-teams?view=azure-bot-service-4.0) ·
[Upload a custom app](https://learn.microsoft.com/en-us/microsoftteams/platform/concepts/deploy-and-publish/apps-upload) ·
[Custom app policies](https://learn.microsoft.com/en-us/microsoftteams/teams-custom-app-policies-and-settings)
