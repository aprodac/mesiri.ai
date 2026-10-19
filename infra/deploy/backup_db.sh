#!/usr/bin/env bash
# Back up the Mesiri Postgres database on the VPS: nightly (mesiri-backup.timer,
# INF-06) and before every migration (deploy.yml, INF-04).
#
# Why: a deploy's automatic rollback reverts the *code* to the previous
# commit, but `alembic upgrade head` has already changed the *schema* by then.
# Without a dump taken first, a bad migration has no way back. This takes
# that dump, so every migration has a restore point.
#
# Usage (on the VPS, as root):
#   infra/deploy/backup_db.sh [label]
#
# Postgres runs in Docker on this VPS (INF-11): the dump is taken inside the
# container that publishes MESIRI_POSTGRES__PORT, with the app's own login from
# /opt/mesiri/.env (the password goes in the environment, never on screen).
# Without such a container it falls back to the host's `postgres` superuser.
# Writes a compressed custom-format dump to $BACKUP_DIR and keeps the newest
# $KEEP of the same label.
#
# Restore (stop the services first):
#   systemctl stop mesiri mesiri-worker
#   docker exec -i -e PGPASSWORD=<pw> mesiri-postgres \
#     pg_restore --clean --if-exists --no-owner -U <user> -d <db> < <dump-file>
#   systemctl start mesiri mesiri-worker
set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/mesiri/.env}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/mesiri}"
KEEP="${KEEP:-14}"
LABEL="${1:-manual}"

env_val() { grep -E "^$1=" "${ENV_FILE}" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' \r' || true; }

DB_NAME="$(env_val MESIRI_POSTGRES__DB)"
DB_NAME="${DB_NAME:-$(env_val MESIRI_POSTGRES__DATABASE)}"
DB_NAME="${DB_NAME:-mesiri}"
DB_USER="$(env_val MESIRI_POSTGRES__USER)"
DB_PORT="$(env_val MESIRI_POSTGRES__PORT)"
PG_CONTAINER="$(docker ps --filter "publish=${DB_PORT:-5432}" --format '{{.Names}}' 2>/dev/null | head -1 || true)"

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
OUT="${BACKUP_DIR}/${DB_NAME}-${STAMP}-${LABEL}.dump"

echo "→ Backing up database '${DB_NAME}' (${PG_CONTAINER:-host postgres}) to ${OUT}"
# Write to a temp name and rename only on success, so a half-written dump is
# never mistaken for a good restore point.
if [ -n "${PG_CONTAINER}" ]; then
  docker exec -e PGPASSWORD="$(env_val MESIRI_POSTGRES__PASSWORD)" "${PG_CONTAINER}" \
    pg_dump --format=custom --no-owner -U "${DB_USER:-postgres}" "${DB_NAME}" > "${OUT}.partial"
else
  sudo -u postgres pg_dump --format=custom --no-owner "${DB_NAME}" > "${OUT}.partial"
fi
# A custom-format dump starts with "PGDMP"; anything else (an error page, an empty
# file) is not a restore point.
if [ "$(head -c 5 "${OUT}.partial")" != "PGDMP" ]; then
  rm -f -- "${OUT}.partial"
  echo "✗ pg_dump did not produce a valid dump" >&2
  exit 1
fi
mv "${OUT}.partial" "${OUT}"
chmod 600 "${OUT}"
echo "✓ Backup written ($(du -h "${OUT}" | cut -f1))"

# Retention per label: deploys happen many times a day, so pre-migration dumps
# must not push out the nightly ones. Keep the newest $KEEP of this label.
ls -1t "${BACKUP_DIR}/${DB_NAME}-"*"-${LABEL}.dump" 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
  echo "  removing old backup ${old}"
  rm -f -- "${old}"
done
