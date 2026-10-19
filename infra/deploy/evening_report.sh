#!/usr/bin/env bash
# Read-only report of the evening review of each site's day (WA-04/05/06) for
# one day: which message each site got, whether it was sent, and the holds
# that kept "Confirm all" back (WA-05 logs them). Changes nothing; prints no
# message text beyond the first line.
#
# Usage (on the VPS, as root):  infra/deploy/evening_report.sh [yyyy-mm-dd]   (default today, India)
set -uo pipefail

ENV_FILE="${ENV_FILE:-/opt/mesiri/.env}"
DAY="$(printf '%s' "${1:-}" | tr -dc 0-9-)"
env_val() { grep -E "^$1=" "${ENV_FILE}" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' \r'; }

DB_NAME="$(env_val MESIRI_POSTGRES__DB)"; DB_NAME="${DB_NAME:-mesiri}"
DB_USER="$(env_val MESIRI_MIGRATION_POSTGRES__USER)"; DB_USER="${DB_USER:-$(env_val MESIRI_POSTGRES__USER)}"
DB_PASS="$(env_val MESIRI_MIGRATION_POSTGRES__PASSWORD)"; DB_PASS="${DB_PASS:-$(env_val MESIRI_POSTGRES__PASSWORD)}"
PG="$(docker ps --filter "publish=$(env_val MESIRI_POSTGRES__PORT | tr -dc 0-9)" --format '{{.Names}}' | head -1)"
[ -n "${PG}" ] || { echo "no Postgres container found"; exit 1; }
q() { printf '\n===== %s =====\n' "$1"; docker exec -e PGPASSWORD="${DB_PASS}" "${PG}" psql -U "${DB_USER}" -d "${DB_NAME}" -P pager=off -c "$2" < /dev/null; }
D="${DAY:+'${DAY}'::date}"; D="${D:-(now() AT TIME ZONE 'Asia/Kolkata')::date}"

q "Projects in the evening review (auto DPR on)" "
SELECT o.name AS company, p.name AS project, p.reporting_cutoff_time AS cutoff, p.dpr_send_deadline AS deadline,
       p.auto_dpr_last_run_on AS cutoff_ran_on
FROM projects p JOIN organizations o ON o.id = p.organization_id
WHERE p.auto_generate_dpr ORDER BY 1, 2;"

q "Evening messages for ${DAY:-today}" "
SELECT o.name AS company, s.name AS site, split_part(n.rule_key, ':', 1) AS step, n.status,
       to_char(n.created_at AT TIME ZONE 'Asia/Kolkata', 'HH24:MI') AS queued_ist,
       left(split_part(n.payload->>'message', E'\n', 1), 70) AS first_line,
       (SELECT string_agg(b->>'title', ' / ') FROM jsonb_array_elements(n.payload->'buttons') b) AS buttons,
       n.skip_reason
FROM notifications n
JOIN organizations o ON o.id = n.organization_id
LEFT JOIN sites s ON s.id = n.site_id
WHERE n.rule_key LIKE 'site_day_%' AND n.occurred_on = ${D}
ORDER BY 1, 2, 3;"

q "Site days for ${DAY:-today}" "
SELECT o.name AS company, s.name AS site, dr.status::text AS status, dr.missing_sections->'blocking' AS missing
FROM daily_reports dr JOIN organizations o ON o.id = dr.organization_id JOIN sites s ON s.id = dr.site_id
WHERE dr.level = 'SITE' AND dr.report_date = ${D} ORDER BY 1, 2;"

echo; echo "===== Holds logged (WA-05) ====="
journalctl -u mesiri-worker -u mesiri --since "$(date -d "${DAY:-today}" +%F) 00:00" --no-pager 2>/dev/null \
  | grep -oE "site_day_review\.(confirm|gap_check|no_update|confirmed|item_[a-z]+|closed)[^\"]*" | sed -E 's/site_id=[0-9a-f-]+/site=…/' | sort | uniq -c | head -40
