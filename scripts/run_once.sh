#!/usr/bin/env bash
# run_once.sh -- one unattended cycle on macOS or Linux.
#
#   bash scripts/run_once.sh [instagram_username]
#
# Weekly, via cron (Sundays 18:00):
#   crontab -e
#   0 18 * * 0 cd /path/to/savebrain && bash scripts/run_once.sh >> vault/_logs/cron.log 2>&1

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -f config.json ]; then
  echo "No config.json. Run: python savebrain.py setup" >&2
  exit 1
fi

USERNAME="${1:-$(python -c 'import json;print(json.load(open("config.json")).get("instagram_username",""))')}"
if [ -z "$USERNAME" ]; then
  echo 'Set "instagram_username" in config.json, or pass it as the first argument' >&2
  exit 1
fi

VAULT="$(python -c 'import json;print(json.load(open("config.json")).get("vault_dir","vault"))')"
mkdir -p "$VAULT/_logs"
LOG="$VAULT/_logs/run_$(date +%Y%m%d_%H%M%S).log"

echo "starting bridge (auto-ingest) -> $LOG"
python savebrain.py auto >"$LOG" 2>&1 &
BRIDGE_PID=$!
sleep 3

URL="https://www.instagram.com/$USERNAME/saved/all-posts/#sb-auto"
echo "opening $URL"
if command -v open >/dev/null 2>&1; then open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
else echo "open this yourself: $URL"; fi

wait "$BRIDGE_PID" || true
echo "done. see $LOG"
