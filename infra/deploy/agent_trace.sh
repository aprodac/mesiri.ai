#!/usr/bin/env bash
# Read-only trace of what the assistant decided, per message (INF-14): which
# tools the model called, with which argument NAMES, and what each answered
# (saved / waiting_for_user / held / noted ...; a failed call with the code's reason,
# digits masked, request 193), plus the parked question, the
# held calls and the parts left "still to do" (WA-57). From the agent_tools
# rows of journey_traces (classic) and agent_api_turn rows (v3). Changes nothing; prints no message text and no
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

# TM-41 (2 Nov): this read only classic's agent_tools rows, so v3 (agent_api_turn) showed "(0 rows)" for every
# message of a v3 company. Both are read now; the summary underneath says why a table is empty.
q "What the assistant decided, per message (last ${HOURS} h, India time; v3 and classic)" "
SELECT to_char(t.created_at AT TIME ZONE 'Asia/Kolkata', 'DD Mon HH24:MI:SS') AS at_ist,
       CASE t.stage WHEN 'agent_api_turn' THEN 'v3' ELSE 'classic' END AS agent,
       right(coalesce(m.sender_wa_id, ''), 4) AS sender,
       m.message_type AS kind,
       CASE WHEN t.stage = 'agent_api_turn' THEN
         (SELECT string_agg(c->>'tool' || coalesce('=' || left(c->'result'->>'status', 24), '') || coalesce(' [by ' || (c->>'by') || ']', ''), '  ')
            FROM jsonb_array_elements(CASE WHEN jsonb_typeof(t.stage_payload::jsonb->'calls') = 'array' THEN t.stage_payload::jsonb->'calls' ELSE '[]'::jsonb END) c)
       ELSE
         (SELECT string_agg(c->>'tool' || '(' || coalesce((SELECT string_agg(a, ',') FROM jsonb_array_elements_text(c->'args') a), '') || ')=' || coalesce(c->>'status', '') || coalesce(' [' || (c->>'reason') || ']', ''), '  ')
            FROM jsonb_array_elements(CASE WHEN jsonb_typeof(t.stage_payload::jsonb->'calls') = 'array' THEN t.stage_payload::jsonb->'calls' ELSE '[]'::jsonb END) c)
       END AS tools,
       CASE WHEN t.stage = 'agent_api_turn' THEN
         concat_ws(' ',
           CASE WHEN t.stage_payload::jsonb ? 'error' THEN 'FAILED ' || (t.stage_payload::jsonb->>'error') || ' -> ' || coalesce(t.stage_payload::jsonb->>'handled', '?') END,
           CASE WHEN jsonb_array_length(coalesce(t.stage_payload::jsonb->'saved', '[]'::jsonb)) > 0 THEN 'saved ' || jsonb_array_length(t.stage_payload::jsonb->'saved') END,
           CASE WHEN jsonb_array_length(coalesce(t.stage_payload::jsonb->'pending', '[]'::jsonb)) > 0 THEN 'waiting ' || jsonb_array_length(t.stage_payload::jsonb->'pending') END,
           CASE WHEN coalesce(t.stage_payload::jsonb->>'asked', '') <> '' THEN 'asked a question' END,
           CASE WHEN t.stage_payload::jsonb ? 'cancelled' THEN 'cancelled' END,
           t.duration_ms || ' ms')
       ELSE concat_ws(' ', 'parked: ' || (t.stage_payload::jsonb->>'parked_by'), 'held: ' || (t.stage_payload::jsonb->>'held'),
                      'still to do: ' || (t.stage_payload::jsonb->>'still_to_do'))
       END AS outcome
FROM journey_traces t
LEFT JOIN inbound_messages m ON m.correlation_id = t.correlation_id
WHERE t.stage IN ('agent_tools', 'agent_api_turn') AND t.created_at > ${SINCE}
ORDER BY t.created_at;"

q "Why the table above has what it has (last ${HOURS} h)" "
SELECT (SELECT count(*) FROM inbound_messages WHERE received_at > ${SINCE}) AS messages,
       (SELECT count(*) FROM journey_traces WHERE stage = 'agent_api_turn' AND created_at > ${SINCE}) AS v3_turns,
       (SELECT count(*) FROM journey_traces WHERE stage = 'agent_tools' AND created_at > ${SINCE}) AS classic_turns,
       (SELECT count(*) FROM inbound_messages WHERE received_at > ${SINCE} AND processing_status = 'failed') AS failed_messages,
       (SELECT to_char(max(received_at) AT TIME ZONE 'Asia/Kolkata', 'DD Mon HH24:MI') FROM inbound_messages) AS last_message_ever_ist;"
