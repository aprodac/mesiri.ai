#!/usr/bin/env bash
# Read-only latency report of the live assistant (B-7): where the time goes
# between a WhatsApp message arriving and its reply.
#
# The same numbers as the control panel's Performance page (journey_traces,
# provider_executions, inbound_messages), for the last HOURS hours, plus the
# slowest messages with their stages. Changes nothing; prints no message text.
#
# Usage (on the VPS, as root):  infra/deploy/perf_report.sh [hours]   (default 6)
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

q "Wall time per message type, received -> processed (last ${HOURS} h)" "
SELECT message_type, count(*) AS n,
       round(avg(EXTRACT(EPOCH FROM (processed_at - received_at)))::numeric, 1) AS avg_s,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (processed_at - received_at))))::numeric, 1) AS p50_s,
       round((percentile_cont(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (processed_at - received_at))))::numeric, 1) AS p95_s
FROM inbound_messages WHERE received_at > ${SINCE} AND processed_at IS NOT NULL
GROUP BY message_type ORDER BY avg_s DESC NULLS LAST;"

q "Journey stages (ms)" "
SELECT stage, count(*) AS n, count(*) FILTER (WHERE NOT succeeded) AS failed,
       round(avg(duration_ms)) AS avg, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms)) AS p50,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)) AS p95, max(duration_ms) AS max
FROM journey_traces WHERE created_at > ${SINCE}
GROUP BY stage ORDER BY avg DESC NULLS LAST;"

q "AI / provider calls (ms)" "
SELECT stage, provider, operation, model, count(*) AS n, count(*) FILTER (WHERE NOT succeeded) AS failed,
       round(avg(latency_ms)) AS avg, round(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)) AS p95
FROM provider_executions WHERE created_at > ${SINCE} AND stage <> 'metered'
GROUP BY stage, provider, operation, model ORDER BY avg DESC NULLS LAST LIMIT 25;"

# The agent's own model rounds are only recorded as usage rows (stage 'metered').
q "Agent model rounds, run_tools (ms; one row per round)" "
SELECT model, count(*) AS rounds, count(DISTINCT correlation_id) AS messages,
       round(avg(latency_ms)) AS avg, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)) AS p50,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)) AS p95, max(latency_ms) AS max
FROM provider_executions WHERE created_at > ${SINCE} AND operation = 'run_tools'
GROUP BY model;"

q "Slowest 8 messages: stages in order (ms)" "
WITH slow AS (
  SELECT correlation_id, message_type, received_at,
         round(EXTRACT(EPOCH FROM (processed_at - received_at))::numeric, 1) AS wall_s
  FROM inbound_messages WHERE received_at > ${SINCE} AND processed_at IS NOT NULL
  ORDER BY processed_at - received_at DESC LIMIT 8)
SELECT s.wall_s, s.message_type, to_char(s.received_at AT TIME ZONE 'Asia/Kolkata', 'HH24:MI') AS at_ist,
       (SELECT string_agg(t.stage || ' ' || t.duration_ms, ' > ' ORDER BY t.created_at)
          FROM journey_traces t WHERE t.correlation_id = s.correlation_id) AS stages,
       (SELECT string_agg(p.operation || ' ' || p.latency_ms, ' > ' ORDER BY p.created_at)
          FROM provider_executions p WHERE p.correlation_id = s.correlation_id
           AND (p.stage <> 'metered' OR p.operation = 'run_tools')) AS ai_calls
FROM slow s ORDER BY s.wall_s DESC;"
