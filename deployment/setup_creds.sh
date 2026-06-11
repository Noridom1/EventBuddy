#!/usr/bin/env bash
# Interactively store GreenNode IAM credentials in .greennode.json.
# The secret is read silently and piped via stdin to save_iam_credentials.sh —
# it never appears in the process args, the shell history, or this terminal.
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
SAVE=".claude/skills/agentbase/scripts/save_iam_credentials.sh"
[ -f "$SAVE" ] || { echo "ERROR: $SAVE not found." >&2; exit 1; }

printf 'GreenNode IAM client_id: '
read -r CLIENT_ID
[ -n "$CLIENT_ID" ] || { echo "ERROR: client_id is required." >&2; exit 1; }

printf 'GreenNode IAM client_secret (hidden): '
read -rs CLIENT_SECRET
echo
[ -n "$CLIENT_SECRET" ] || { echo "ERROR: client_secret is required." >&2; exit 1; }

printf '%s' "$CLIENT_SECRET" | bash "$SAVE" --client-id "$CLIENT_ID" --secret-stdin
unset CLIENT_SECRET

echo "Verifying..."
bash .claude/skills/agentbase/scripts/check_credentials.sh iam
