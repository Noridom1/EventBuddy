# EventBuddy — Teams app package

This folder builds the sideloadable / publishable Teams app package (`eventbuddy.zip`):

```
teams-app/
├── manifest.json   # app definition (schema v1.17)
├── color.png       # 192×192 full-color icon  (PLACEHOLDER — swap for real branding)
├── outline.png     # 32×32 transparent monochrome icon (PLACEHOLDER)
├── build.sh        # zips the three files above into eventbuddy.zip
└── eventbuddy.zip  # the installable package (output of build.sh)
```

## Identity & domains (already configured)

`manifest.json` is release-ready: the Teams app `id` and the bot `botId` are set to the real
Entra Application (client) IDs and `version` is `1.0.3`. The `validDomains` list covers the live
AgentBase endpoint host (`endpoint-0a09ccce-…vngcloud.vn`) plus the Bot Framework / Entra login
domains used by the sign-in-card OAuth flow. If the endpoint or those IDs change, edit
`manifest.json` and rebuild.

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
- You can also import this `manifest.json` into the **Teams Developer Portal**
  (dev.teams.microsoft.com) to validate and package it visually.
