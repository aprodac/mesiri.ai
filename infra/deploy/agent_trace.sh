#!/usr/bin/env bash
# Read-only trace of what the assistant decided, per message (INF-14): which
# tools the model called, with which argument NAMES, and what each answered
# (saved / waiting_for_user / held / noted ...), plus the parked question, the
# held calls and the parts left "still to do" (WA-57). From the agent_tools
# rows of journey_traces. Changes nothing; prints no message text and no
# argument values; the sender is shown by the last 4 digits of the number.
#
# Usage (on the VPS, as root):  infra/deploy/agent_trace.sh [hours]   (default 6)
set -uo pipefail

ENV_FILE="${ENV_FILE:-/opt/mesiri/.env}"
HOURS="$(printf '%s' "${1:-6}" | tr -dc 0-9)"; HOURS="${HOURS:-6}"

env_val() { grep -E "^$1=" "${ENV_FILE}" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' \r'; }

DB_NAME="$(env_val MESIRI_POSTGRES__DB)"; DB_NAME="${DB_NAME:-mesiri}"
DB_USER="$(env_val MESIRI_MIGRATION_POSTGRES__USER)"; DB_USER="${DB_USER:-$(env_val MESIRI_POSTGRES__USER)}"
DB_PASS="$(env_val MESIRI_MIGRATION_POSTGRES__PASSWORD)"; DB_PASS="${DB_PASS:-$(env_val MESIRI_POSTGRES__PASSWORD)}"
PG="$(docker ps --filter "publish=$(env_val MESIRI_POSTGRES__PORT | tr -dc 0-9)" --format '{{.Names}}' | head -1)"
[ -n "${PG}" ] || { echo "no Postgres container found"; exit 1; }
q() { printf '\n===== %s =====\n' "$1"; docker exec -e PGPASSWORD="${DB_PASS}" "${PG}" psql -U "${DB_USER}" -d "${DB_NAME}" -P pager=off -c "$2" < /dev/null; }
SINCE="now() - interval '${HOURS} hours'"

q "What the assistant decided, per message (last ${HOURS} h, India time)" "
SELECT to_char(t.created_at AT TIME ZONE 'Asia/Kolkata', 'DD Mon HH24:MI:SS') AS at_ist,
       right(coalesce(m.sender_wa_id, ''), 4) AS sender,
       m.message_type AS kind,
       (SELECT string_agg(c->>'tool' || '(' || coalesce((SELECT string_agg(a, ',') FROM jsonb_array_elements_text(c->'args') a), '') || ')=' || coalesce(c->>'status', ''), '  ')
          FROM jsonb_array_elements(t.stage_payload::jsonb->'calls') c) AS tools,
       t.stage_payload::jsonb->>'parked_by' AS parked,
       t.stage_payload::jsonb->'held' AS held,
       t.stage_payload::jsonb->'still_to_do' AS still_to_do
FROM journey_traces t
LEFT JOIN inbound_messages m ON m.correlation_id = t.correlation_id
WHERE t.stage = 'agent_tools' AND t.created_at > ${SINCE}
ORDER BY t.created_at;"
