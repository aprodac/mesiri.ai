#!/usr/bin/env bash
# Back up the Mesiri Postgres database on the VPS before a migration runs.
#
# Why: a deploy's automatic rollback reverts the *code* to the previous
# commit, but `alembic upgrade head` has already changed the *schema* by then.
# Without a dump taken first, a bad migration has no way back. This takes
# that dump, so every migration has a restore point.
#
# Usage (on the VPS, as root):
#   infra/deploy/backup_db.sh [label]
#
# Reads the database name from /opt/mesiri/.env (MESIRI_POSTGRES__DATABASE,
# default "mesiri") and connects as the local `postgres` superuser, so no
# password is needed or printed. Writes a compressed custom-format dump to
# $BACKUP_DIR and keeps the newest $KEEP of them.
#
# Restore (stop the services first):
#   systemctl stop mesiri mesiri-worker
#   sudo -u postgres pg_restore --clean --if-exists -d <db> <dump-file>
#   systemctl start mesiri mesiri-worker
set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/mesiri/.env}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/mesiri}"
KEEP="${KEEP:-14}"
LABEL="${1:-manual}"

DB_NAME="$(grep -E '^MESIRI_POSTGRES__DATABASE=' "${ENV_FILE}" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' \r' || true)"
DB_NAME="${DB_NAME:-mesiri}"

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
OUT="${BACKUP_DIR}/${DB_NAME}-${STAMP}-${LABEL}.dump"

echo "→ Backing up database '${DB_NAME}' to ${OUT}"
# Write to a temp name and rename only on success, so a half-written dump is
# never mistaken for a good restore point.
sudo -u postgres pg_dump --format=custom --no-owner "${DB_NAME}" > "${OUT}.partial"
mv "${OUT}.partial" "${OUT}"
chmod 600 "${OUT}"
echo "✓ Backup written ($(du -h "${OUT}" | cut -f1))"

# Retention: keep the newest $KEEP dumps for this database, delete the rest.
ls -1t "${BACKUP_DIR}/${DB_NAME}-"*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
  echo "  removing old backup ${old}"
  rm -f -- "${old}"
done
