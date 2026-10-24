#!/usr/bin/env bash
# Uptime check, run from outside the VPS every 10 minutes by
# .github/workflows/uptime.yml (INF-08). Is Mesiri up for a customer right now?
#
#   1. the API answers and reports ok        (api /health)
#   2. the WhatsApp worker is alive           (api /health "worker")
#   3. the dashboard loads                    (app.whatsapp.mesiri.ai)
#   4. the control panel loads                (api /mesiriadmin/, which redirects
#                                               to control.mesiri.ai once INF-15 is live)
#
# Each check is tried 3 times, 20 s apart, before it counts as down, so a
# deploy restart or a network blip does not wake anyone. Prints one line per
# check; exits 1 if any is down. Reads only.
#
# Usage: infra/deploy/uptime_check.sh [api-url] [dashboard-url]
set -uo pipefail

API_URL="${1:-https://api.whatsapp.mesiri.ai}"
DASHBOARD_URL="${2:-https://app.whatsapp.mesiri.ai}"
ATTEMPTS="${UPTIME_ATTEMPTS:-3}"
PAUSE="${UPTIME_PAUSE_SECONDS:-20}"

FAILED=0

# try <label> <command...>: run the command up to ATTEMPTS times.
try() {
  local label="$1"; shift
  local i
  for ((i = 1; i <= ATTEMPTS; i++)); do
    if "$@"; then echo "  ✓ ${label}"; return 0; fi
    [ "$i" -lt "$ATTEMPTS" ] && sleep "$PAUSE"
  done
  echo "  ✗ ${label}"
  FAILED=1
}

http_ok() { curl -fsSL -m 15 -o /dev/null "$1" 2>/dev/null; }

api_ok() {
  curl -fsS -m 15 "${API_URL}/health" 2>/dev/null | python3 -c \
    'import json,sys; sys.exit(0 if json.load(sys.stdin).get("status") == "ok" else 1)' 2>/dev/null
}

# "off" means this build has no queue (never in production) or predates the
# field; only an explicit "down" is an outage.
worker_ok() {
  curl -fsS -m 15 "${API_URL}/health" 2>/dev/null | python3 -c \
    'import json,sys; sys.exit(1 if json.load(sys.stdin).get("worker") == "down" else 0)' 2>/dev/null
}

try "API (${API_URL}/health)" api_ok
# The worker's status is read through the API: with the API down it is unknown.
if [ "$FAILED" -eq 0 ]; then
  try "WhatsApp worker" worker_ok
else
  echo "  ? WhatsApp worker (unknown while the API is down)"
fi
try "Dashboard (${DASHBOARD_URL})" http_ok "${DASHBOARD_URL}/"
try "Control panel (${API_URL}/mesiriadmin/)" http_ok "${API_URL}/mesiriadmin/"

exit "$FAILED"
