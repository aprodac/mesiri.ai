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

# Speech-to-text, image reading and the like: every AI call recorded as usage
# only (stage 'metered'), not just the agent's rounds above.
q "All AI calls recorded as usage, by operation (ms)" "
SELECT operation, model, count(*) AS n,
       round(avg(latency_ms)) AS avg, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)) AS p50,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)) AS p95
FROM provider_executions WHERE created_at > ${SINCE} AND stage = 'metered' AND latency_ms IS NOT NULL
GROUP BY operation, model ORDER BY avg DESC NULLS LAST LIMIT 25;"

# Meta's send timestamp is whole seconds and received_at is written once the
# worker has the message, so this is Meta's delivery plus our pickup, +-1 s.
q "Sender pressed send -> message logged by us (s)" "
WITH d AS (
  SELECT message_type,
         EXTRACT(EPOCH FROM (received_at - to_timestamp((raw_payload->'message'->>'timestamp')::bigint))) AS s
  FROM inbound_messages
  WHERE received_at > ${SINCE} AND raw_payload->'message'->>'timestamp' ~ '^[0-9]+$')
SELECT message_type, count(*) AS n, round(avg(s)::numeric, 1) AS avg_s,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY s))::numeric, 1) AS p50_s,
       round((percentile_cont(0.95) WITHIN GROUP (ORDER BY s))::numeric, 1) AS p95_s
FROM d GROUP BY message_type ORDER BY avg_s DESC NULLS LAST;"

q "Average step laps per message type (ms; steps averaging 50 ms or more)" "
SELECT m.message_type, e.k AS step, count(*) AS n,
       round(avg(e.v::numeric)) AS avg, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY e.v::numeric)) AS p50,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY e.v::numeric)) AS p95
FROM journey_traces t
JOIN inbound_messages m ON m.correlation_id = t.correlation_id
CROSS JOIN LATERAL jsonb_each_text(t.stage_payload::jsonb) AS e(k, v)
WHERE t.stage = 'prepipeline' AND t.created_at > ${SINCE} AND e.v ~ '^[0-9.]+$'
GROUP BY m.message_type, e.k HAVING avg(e.v::numeric) >= 50
ORDER BY m.message_type, avg DESC;"

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

q "Slowest 8 messages: where the time inside the journey went (step laps, ms)" "
SELECT t.duration_ms AS total, to_char(t.created_at AT TIME ZONE 'Asia/Kolkata', 'HH24:MI') AS at_ist,
       (SELECT string_agg(k || ' ' || round(v::numeric), ' > ' ORDER BY v::numeric DESC)
          FROM jsonb_each_text(t.stage_payload::jsonb) AS e(k, v)
         WHERE v ~ '^[0-9.]+$' AND v::numeric >= 100) AS laps_over_100ms
FROM journey_traces t
WHERE t.stage = 'prepipeline' AND t.created_at > ${SINCE}
ORDER BY t.duration_ms DESC LIMIT 8;"
