#!/usr/bin/env bash
# Read-only: a project's sites (name, status) and its members' site access, by
# project name (case-insensitive substring). Names and counts only; no phone
# numbers, no message text. Why a sender gets (or does not get) site buttons.
#
# Usage (on the VPS, as root):  infra/deploy/scope_report.sh "<project name>"
set -uo pipefail

ENV_FILE="${ENV_FILE:-/opt/mesiri/.env}"
NAME="$(printf '%s' "${1:-}" | tr -dc '[:alnum:] _-')"
[ -n "${NAME}" ] || { echo "usage: scope_report.sh <project name>"; exit 2; }

env_val() { grep -E "^$1=" "${ENV_FILE}" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' \r'; }
DB_NAME="$(env_val MESIRI_POSTGRES__DB)"; DB_NAME="${DB_NAME:-mesiri}"
DB_USER="$(env_val MESIRI_MIGRATION_POSTGRES__USER)"; DB_USER="${DB_USER:-$(env_val MESIRI_POSTGRES__USER)}"
DB_PASS="$(env_val MESIRI_MIGRATION_POSTGRES__PASSWORD)"; DB_PASS="${DB_PASS:-$(env_val MESIRI_POSTGRES__PASSWORD)}"
PG="$(docker ps --filter "publish=$(env_val MESIRI_POSTGRES__PORT | tr -dc 0-9)" --format '{{.Names}}' | head -1)"
[ -n "${PG}" ] || { echo "no Postgres container found"; exit 1; }
q() { printf '\n===== %s =====\n' "$1"; docker exec -e PGPASSWORD="${DB_PASS}" "${PG}" psql -U "${DB_USER}" -d "${DB_NAME}" -P pager=off -c "$2" < /dev/null; }

q "Projects" "SELECT p.name, p.status, o.name AS company, (SELECT count(*) FROM sites s WHERE s.project_id = p.id) AS sites
FROM projects p JOIN organizations o ON o.id = p.organization_id WHERE p.name ILIKE '%${NAME}%';"
q "Sites" "SELECT p.name AS project, s.name AS site, s.status FROM sites s JOIN projects p ON p.id = s.project_id
WHERE p.name ILIKE '%${NAME}%' ORDER BY 1, 2;"
q "Members (role, site access)" "SELECT p.name AS project, u.role, pm.site_access_mode, count(*) AS n
FROM project_members pm JOIN projects p ON p.id = pm.project_id JOIN users u ON u.id = pm.user_id
WHERE p.name ILIKE '%${NAME}%' GROUP BY 1, 2, 3 ORDER BY 1, 2;"
