#!/usr/bin/env bash
# End-to-end smoke test of the HITL action plane over the dev HTTP routes — works against a
# LOCAL run or a DEPLOYED AgentBase endpoint, with NO Bot Framework Emulator and NO ngrok
# (the dev routes are synchronous request/response, unlike /api/messages).
#
# Drives: reset → focus → list tasks → update task → prepare reminders (capture pending_id)
#         → confirm. Assumes `make seed` has populated the "Demo Workshop" event and that the
#         deployed runtime has DEV_ROUTES_ENABLED=true + the LLM (MaaS) path wired.
#
# Usage:  scripts/smoke.sh <base-url> [user-id]
set -euo pipefail

BASE="${1:?usage: smoke.sh <base-url> [user-id]}"
USER="${2:-dev-user}"
BASE="${BASE%/}"

handle() {  # $1 = text, $2 = extra JSON fields (optional) — echoes the raw JSON response
  curl -fsS "$BASE/api/dev/handle" -H 'content-type: application/json' \
    -d "{\"user_id\":\"$USER\",\"text\":$(printf '%s' "$1" | jq -Rs .)${2:-}}"
}

echo "▶ reset";        handle "hi" ",\"reset\":true"            | jq -r '.reply // .error'
echo "▶ focus";        handle "focus on Demo Workshop"          | jq -r '.reply // .error'
echo "▶ my tasks";     handle "what are my tasks?"              | jq -r '.reply // .error'
echo "▶ update task";  handle "mark Book the room as done"      | jq -r '.reply // .error'

echo "▶ prepare reminders"
PREP="$(handle 'remind everyone about the slides')"
echo "$PREP" | jq -r '.reply // .error'
PID="$(echo "$PREP" | jq -r '.cards[0].actions[0].data.pending_id // empty')"
if [ -z "$PID" ]; then
  echo "  (no card emitted — is the event seeded and the LLM path enabled?)"; exit 0
fi
echo "  pending_id=$PID"

echo "▶ confirm (outlook)"
curl -fsS "$BASE/api/dev/confirm" -H 'content-type: application/json' \
  -d "{\"user_id\":\"$USER\",\"action\":\"remind\",\"channel\":\"outlook\",\"pending_id\":\"$PID\"}" \
  | jq -r '.reply // .error'

echo "▶ confirm again (replay guard — expect 'expired')"
curl -fsS "$BASE/api/dev/confirm" -H 'content-type: application/json' \
  -d "{\"user_id\":\"$USER\",\"action\":\"remind\",\"channel\":\"outlook\",\"pending_id\":\"$PID\"}" \
  | jq -r '.reply // .error'
