#!/usr/bin/env bash
# Deploy a commit to STAGING on the VPS and prove it before production (INF-02, INF-03).
#
# Staging is a second copy of the app on the same server, reachable only from
# the server itself (127.0.0.1:${STAGING_PORT}), with:
#   - its own checkout and venv          /opt/mesiri-staging
#   - a fresh copy of production's data   database mesiri_staging, re-copied on
#                                         every run, so each migration is tried
#                                         on real data before it touches prod
#   - production's .env, with overrides   no WhatsApp sending (Graph API pointed
#                                         at a closed local port, token blanked),
#                                         automations off, own Redis DB, own
#                                         media folder, own port
# There is no staging worker: no webhook ever reaches staging, so nothing is
# queued. Idempotent: the first run sets everything up.
#
# Usage (on the VPS, as root):   infra/deploy/staging_deploy.sh [git-ref]   (default origin/main)
# Exits non-zero on the first failure; production is never touched.
set -euo pipefail

PROD=/opt/mesiri
STG=/opt/mesiri-staging
PORT="${STAGING_PORT:-8101}"
REF="${1:-origin/main}"
UV="${UV:-$HOME/.local/bin/uv}"
STG_DB=mesiri_staging

env_val() { grep -E "^$1=" "$2" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' \r' || true; }

echo "── Staging deploy $(date -u '+%Y-%m-%dT%H:%M:%SZ') (${REF}) ──"

echo "→ Code"
if [ ! -d "${STG}/.git" ]; then
  # Same stored GitHub credential as the production checkout (deploy.yml writes it).
  git -c credential.helper=store clone --quiet "$(git -C "${PROD}" remote get-url origin)" "${STG}"
  git -C "${STG}" config credential.helper store
fi
git -C "${STG}" fetch --quiet --prune origin
git -C "${STG}" reset --quiet --hard "${REF}"
SHA="$(git -C "${STG}" rev-parse --short HEAD)"
echo "  ${SHA}"

echo "→ Dependencies"
[ -x "${STG}/.venv/bin/python" ] || "${UV}" venv --quiet --python 3.11 "${STG}/.venv"
(cd "${STG}" && "${UV}" pip install --quiet --python "${STG}/.venv/bin/python" -e ".[infra,providers,workflow,receipt,reports]")
for SRC in shared/contracts/src platform/ai/src backend/src backend/migrations apps/whatsapp-assistant/src; do
  find "${STG}/${SRC}" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
done

echo "→ Settings (production's, made safe)"
REDIS_DB="$(env_val MESIRI_REDIS__DB "${PROD}/.env")"
{
  grep -vE '^(MESIRI_POSTGRES__DB|MESIRI_POSTGRES__DATABASE|MESIRI_APP_PORT|MESIRI_REDIS__DB|MESIRI_AUTOMATIONS__ENABLED|MESIRI_OBJECT_STORAGE__LOCAL_ROOT|MESIRI_OBJECT_STORAGE__PUBLIC_BASE_URL|WHATSAPP_ACCESS_TOKEN|WHATSAPP_GRAPH_BASE_URL)=' "${PROD}/.env"
  echo "# ── staging overrides (infra/deploy/staging_deploy.sh) ──"
  # The app reads MESIRI_POSTGRES__DATABASE (PostgresSettings.database); __DB
  # alone was ignored, so staging migrated and ran on production's database.
  echo "MESIRI_POSTGRES__DB=${STG_DB}"
  echo "MESIRI_POSTGRES__DATABASE=${STG_DB}"
  echo "MESIRI_APP_PORT=${PORT}"
  echo "MESIRI_REDIS__DB=$(( ${REDIS_DB:-0} + 1 ))"
  echo "MESIRI_AUTOMATIONS__ENABLED=false"
  echo "MESIRI_OBJECT_STORAGE__LOCAL_ROOT=/var/lib/mesiri-staging/media"
  echo "MESIRI_OBJECT_STORAGE__PUBLIC_BASE_URL=http://127.0.0.1:${PORT}"
  echo "WHATSAPP_ACCESS_TOKEN=staging-sends-nothing"
  echo "WHATSAPP_GRAPH_BASE_URL=http://127.0.0.1:9"
} > "${STG}/.env.new"
chmod 600 "${STG}/.env.new"
mv "${STG}/.env.new" "${STG}/.env"
mkdir -p /var/lib/mesiri-staging/media

echo "→ Fresh copy of production's data"
systemctl stop mesiri-staging 2>/dev/null || true
# The owner login (BE-03 keeps it as MESIRI_MIGRATION_POSTGRES__* once the app
# uses mesiri_app, which may not create databases or read past row-level security).
DB_USER="$(env_val MESIRI_MIGRATION_POSTGRES__USER "${PROD}/.env")"
DB_USER="${DB_USER:-$(env_val MESIRI_POSTGRES__USER "${PROD}/.env")}"; DB_USER="${DB_USER:-postgres}"
DB_PASS="$(env_val MESIRI_MIGRATION_POSTGRES__PASSWORD "${PROD}/.env")"
DB_PASS="${DB_PASS:-$(env_val MESIRI_POSTGRES__PASSWORD "${PROD}/.env")}"
PROD_DB="$(env_val MESIRI_POSTGRES__DB "${PROD}/.env")"; PROD_DB="${PROD_DB:-mesiri}"
PG="$(docker ps --filter "publish=$(env_val MESIRI_POSTGRES__PORT "${PROD}/.env" | tr -dc 0-9)" --format '{{.Names}}' | head -1)"
[ -n "${PG}" ] || { echo "✗ no Postgres container found"; exit 1; }
# Only the restore reads stdin (-i); the rest get /dev/null, so nothing can swallow
# this script when it is piped to bash.
pg() { docker exec -e PGPASSWORD="${DB_PASS}" "${PG}" "$@" < /dev/null; }
pg_in() { docker exec -i -e PGPASSWORD="${DB_PASS}" "${PG}" "$@"; }
pg dropdb --if-exists -U "${DB_USER}" "${STG_DB}"
pg createdb -U "${DB_USER}" "${STG_DB}"
pg pg_dump --format=custom --no-owner -U "${DB_USER}" "${PROD_DB}" \
  | pg_in pg_restore --no-owner --exit-on-error -U "${DB_USER}" -d "${STG_DB}"
echo "  copied ${PROD_DB} → ${STG_DB}"

echo "→ Migrations on the copy"
cd "${STG}"
# Never migrate anything but the copy: stop if the settings resolve elsewhere.
RESOLVED_DB="$("${STG}/.venv/bin/python" -c 'from mesiri.bootstrap.settings import get_settings; print(get_settings().postgres.database)')"
if [ "${RESOLVED_DB}" != "${STG_DB}" ]; then
  echo "✗ staging settings point at database '${RESOLVED_DB}', not ${STG_DB}; stopping" >&2
  exit 1
fi
MIG_USER="$(env_val MESIRI_MIGRATION_POSTGRES__USER .env)"
MIG_PASS="$(env_val MESIRI_MIGRATION_POSTGRES__PASSWORD .env)"
if [ -n "${MIG_USER}" ]; then
  MESIRI_POSTGRES__USER="${MIG_USER}" MESIRI_POSTGRES__PASSWORD="${MIG_PASS}" \
    "${STG}/.venv/bin/alembic" -c backend/alembic.ini upgrade head
else
  "${STG}/.venv/bin/alembic" -c backend/alembic.ini upgrade head
fi
unset MIG_USER MIG_PASS

echo "→ Service"
cp "${STG}/infra/mesiri-staging.service" /etc/systemd/system/mesiri-staging.service
systemctl daemon-reload
systemctl restart mesiri-staging
for i in $(seq 1 30); do
  sleep 2
  if curl -sf "http://127.0.0.1:${PORT}/health/live" > /dev/null; then
    echo "  ✓ up after ~$((i * 2)) s"
    break
  fi
  if [ "${i}" = 30 ]; then
    echo "✗ staging did not come up"
    journalctl -u mesiri-staging -n 80 --no-pager || true
    exit 1
  fi
done

echo "→ Smoke test"
ENV_FILE="${STG}/.env" SKIP_WORKER=1 bash "${STG}/infra/deploy/smoke_test.sh" "${SHA}" "http://127.0.0.1:${PORT}"
echo "✓ Staging ${SHA} passed"
