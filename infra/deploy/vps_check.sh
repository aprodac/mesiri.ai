#!/usr/bin/env bash
# Read-only health and configuration check of the Mesiri VPS (tracker INF-01,
# BE-30, BE-31, INF-09).
#
# Changes nothing. Never prints a secret: for sensitive settings it prints only
# whether they are set, and whether they still hold the code's default.
#
# Usage (on the VPS, as root), then paste the whole output back:
#   bash /opt/mesiri/infra/deploy/vps_check.sh 2>&1 | tee /tmp/vps_check.txt
set -uo pipefail

ENV_FILE="${ENV_FILE:-/opt/mesiri/.env}"

section() { printf '\n===== %s =====\n' "$1"; }
env_val() { grep -E "^$1=" "${ENV_FILE}" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' \r'; }

section "Machine"
hostname; uname -r; uptime; nproc
free -h
df -h -x tmpfs -x devtmpfs

section "Mesiri services"
systemctl list-units --all --no-pager 'mesiri*' 'nginx*' 'postgresql*' 'redis*'

section "Timers and cron (to avoid double-running jobs, INF-05)"
systemctl list-timers --all --no-pager
echo "--- root crontab"; crontab -l 2>&1
echo "--- /etc/cron.d"; ls -la /etc/cron.d 2>&1
for f in /etc/cron.d/*; do [ -f "$f" ] && { echo "--- $f"; grep -v '^#' "$f" | grep -v '^$'; }; done

section "Listening ports"
ss -tlnp

section "Databases"
sudo -u postgres psql -At -c "SELECT datname, pg_size_pretty(pg_database_size(datname)) FROM pg_database WHERE NOT datistemplate ORDER BY 1"

section "Backups"
ls -la /var/backups/mesiri 2>&1 | tail -20
echo "--- other recent dump files (last 30 days)"
find / -xdev \( -name '*.dump' -o -name '*.sql.gz' -o -name '*.sql' \) -mtime -30 -size +100k 2>/dev/null | head -20

section "Configuration (names only; secrets are never printed)"
echo "Variables set in ${ENV_FILE}:"
grep -E '^[A-Z_][A-Z0-9_]*=' "${ENV_FILE}" 2>/dev/null | cut -d= -f1 | sort
echo
echo "MESIRI_ENVIRONMENT = '$(env_val MESIRI_ENVIRONMENT)'  (empty means the code default, which is not production)"
echo "MESIRI_OBJECT_STORAGE__PROVIDER = '$(env_val MESIRI_OBJECT_STORAGE__PROVIDER)'"
jwt="$(env_val MESIRI_JWT_SECRET)"
if [ -z "${jwt}" ]; then
  echo "MESIRI_JWT_SECRET: NOT SET  <-- tokens are signed with the public default in the code"
elif [ "${jwt}" = "mesiri-temp-secret-key-change-in-production" ]; then
  echo "MESIRI_JWT_SECRET: SET BUT STILL THE PUBLIC DEFAULT"
else
  echo "MESIRI_JWT_SECRET: set, ${#jwt} characters, not the default"
fi
pg="$(env_val MESIRI_POSTGRES__PASSWORD)"
[ "${pg}" = "mesiri_local_dev" ] && echo "MESIRI_POSTGRES__PASSWORD: STILL THE LOCAL DEFAULT"

section "Running app"
APP_PORT="$(env_val MESIRI_APP_PORT)"; curl -s -m 10 "http://127.0.0.1:${APP_PORT:-8000}/health"; echo

section "Platform-admin accounts (BE-30): role ADMIN with no company"
DB_NAME="$(env_val MESIRI_POSTGRES__DATABASE)"; DB_NAME="${DB_NAME:-mesiri}"
sudo -u postgres psql -d "${DB_NAME}" -c \
  "SELECT id, email, status, created_at FROM users WHERE role = 'ADMIN' AND organization_id IS NULL ORDER BY created_at"

section "WhatsApp numbers held by more than one user (BE-04): migration 0483 stops if any"
sudo -u postgres psql -d "${DB_NAME}" -c \
  "SELECT regexp_replace(whatsapp_number, '\\D', '', 'g') AS digits, count(*) AS users FROM users WHERE whatsapp_number IS NOT NULL AND regexp_replace(whatsapp_number, '\\D', '', 'g') <> '' GROUP BY 1 HAVING count(*) > 1"

section "Done"
