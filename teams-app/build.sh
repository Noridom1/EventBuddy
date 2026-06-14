#!/usr/bin/env bash
# Build the EventBuddy Teams app package (eventbuddy.zip).
# The three files must sit at the ROOT of the zip — no subfolder.
set -euo pipefail
cd "$(dirname "$0")"

if grep -q "REPLACE_WITH_ENTRA_APP_ID" manifest.json; then
  echo "WARNING: manifest.json still has REPLACE_WITH_ENTRA_APP_ID — Teams will reject upload."
  echo "         Set both 'id' and 'bots[0].botId' to the Entra App ID from IT, then rebuild."
fi

rm -f eventbuddy.zip
if command -v zip >/dev/null 2>&1; then
  zip -j eventbuddy.zip manifest.json color.png outline.png
else
  python3 - <<'PY'
import zipfile
with zipfile.ZipFile("eventbuddy.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for f in ("manifest.json", "color.png", "outline.png"):
        z.write(f, arcname=f)
print("eventbuddy.zip written (python fallback)")
PY
fi
echo "Built: $(pwd)/eventbuddy.zip"
