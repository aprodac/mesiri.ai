#!/usr/bin/env bash
# Nightly backup of the teammate inbox (TM-08): every group's messages,
# transcripts / translations, the request log, the media files, and the
# WhatsApp session (so a restore needs no re-pairing).
#
# Installed by .github/workflows/teammate-deploy.yml as teammate-backup.timer
# (02:30 IST). Same pattern as infra/deploy/backup_db.sh: root-only folder,
# written under a temporary name, newest $KEEP kept.
#
# Restore (as root):
#   systemctl stop teammate
#   tar -xzf /var/backups/teammate/teammate-<stamp>.tar.gz -C /var/lib/teammate
#   systemctl start teammate
set -euo pipefail

DATA_DIR="${DATA_DIR:-/var/lib/teammate}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/teammate}"
KEEP="${KEEP:-14}"
NODE="${NODE:-$(command -v node || echo /usr/bin/node)}"

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"
STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
OUT="${BACKUP_DIR}/teammate-${STAMP}.tar.gz"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

# A consistent copy of the live database (safe while the listener writes).
"${NODE}" --no-warnings -e '
  const { DatabaseSync } = require("node:sqlite");
  const db = new DatabaseSync(process.argv[1], { readOnly: true });
  db.exec("VACUUM INTO " + JSON.stringify(process.argv[2]).replace(/"/g, "\x27"));
  db.close();
' "${DATA_DIR}/inbox.db" "${TMP}/inbox.db"

tar -czf "${OUT}.partial" -C "${TMP}" inbox.db -C "${DATA_DIR}" media auth
mv "${OUT}.partial" "${OUT}"
echo "→ ${OUT} ($(du -h "${OUT}" | cut -f1))"

ls -1t "${BACKUP_DIR}"/teammate-*.tar.gz | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "→ keeping $(ls -1 "${BACKUP_DIR}"/teammate-*.tar.gz | wc -l) backup(s) in ${BACKUP_DIR}"
