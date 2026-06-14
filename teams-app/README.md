# EventBuddy — Teams app package

This folder builds the sideloadable / publishable Teams app package (`eventbuddy.zip`):

```
teams-app/
├── manifest.json   # app definition (schema v1.17)
├── color.png       # 192×192 full-color icon  (PLACEHOLDER — swap for real branding)
├── outline.png     # 32×32 transparent monochrome icon (PLACEHOLDER)
└── build.sh        # zips the three files above into eventbuddy.zip
```

## Before you build — one required edit

`manifest.json` has **two** `REPLACE_WITH_ENTRA_APP_ID` placeholders (`id` and `bots[0].botId`).
Both must be set to the **Entra Application (client) ID** that IT creates for the bot. They are
the same value. Until that GUID exists you can build the zip, but Teams will reject it on upload.

The `validDomains` entry is already set to the live AgentBase endpoint host
(`endpoint-0a09ccce-…vngcloud.vn`). If the endpoint changes, update it here too.

## Build

```bash
bash teams-app/build.sh        # → teams-app/eventbuddy.zip
```

## Upload (after IT enables custom app upload)

Teams client → **Apps → Manage your apps → Upload an app → Upload a custom app** →
pick `eventbuddy.zip` → add it to your **test team** (not org-wide).

## Notes

- Icons here are valid placeholders (a blue tile + a white-ring outline). Replace them with real
  artwork before any wider rollout — keep the same filenames and dimensions (192×192 color,
  32×32 transparent outline).
- The `ChannelMessage.Read.Group` RSC permission is declared so the team owner consents to
  channel-read at install time (scoped to that team only). Add more RSC entries
  (e.g. `ChannelMessage.Send.Group`) as you enable channel features.
- You can also import this `manifest.json` into the **Teams Developer Portal**
  (dev.teams.microsoft.com) to validate and package it visually.
