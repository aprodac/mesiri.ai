#!/usr/bin/env bash
# BE-03 step 3: the app and worker log into Postgres as `mesiri_app` -- not
# a superuser, can't bypass row-level security -- so migration 0484's
# policies apply. Migrations keep the owner login (deploy.yml reads it from
# MESIRI_MIGRATION_POSTGRES__USER/PASSWORD). Design:
# docs/backend/tenant-isolation.md.
#
# Never prints a password.
#
# Usage (on the VPS, as root):
#   bash /opt/mesiri/infra/deploy/app_db_login.sh check     # read-only: where things stand
#   bash /opt/mesiri/infra/deploy/app_db_login.sh switch    # create the login, switch, restart, health check
#   bash /opt/mesiri/infra/deploy/app_db_login.sh rollback  # put the previous .env back and restart
#
# `switch` backs up .env first, creates the login with a new random password
# (re-running it after a rollback just resets that password), and rolls
# itself back if /health fails.
set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/mesiri/.env}"
APP_ROLE="mesiri_app"
BACKUP_GLOB="${ENV_FILE}.before-be03-*"

env_val() { grep -E "^$1=" "${ENV_FILE}" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' \r'; }
die() { echo "ERROR: $*" >&2; exit 1; }

[ -f "${ENV_FILE}" ] || die "${ENV_FILE} not found"

HOST="$(env_val MESIRI_POSTGRES__HOST)"; HOST="${HOST:-localhost}"
PORT="$(env_val MESIRI_POSTGRES__PORT)"; PORT="${PORT:-5432}"
DB="$(env_val MESIRI_POSTGRES__DATABASE)"; DB="${DB:-mesiri}"
APP_PORT="$(env_val MESIRI_APP_PORT)"; APP_PORT="${APP_PORT:-8000}"

# The owner login: the migration login once switched, else the current one.
owner_user() { local u; u="$(env_val MESIRI_MIGRATION_POSTGRES__USER)"; echo "${u:-$(env_val MESIRI_POSTGRES__USER)}"; }
owner_pass() { local p; p="$(env_val MESIRI_MIGRATION_POSTGRES__PASSWORD)"; echo "${p:-$(env_val MESIRI_POSTGRES__PASSWORD)}"; }

owner_psql() {
  PGPASSWORD="$(owner_pass)" psql -h "${HOST}" -p "${PORT}" -U "$(owner_user)" -d "${DB}" \
    -v ON_ERROR_STOP=1 -X -q "$@"
}

health() {
  local i
  for i in $(seq 1 30); do
    if curl -fsS -m 5 "http://127.0.0.1:${APP_PORT}/health" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  return 1
}

restart() {
  systemctl restart mesiri
  systemctl restart mesiri-worker 2>/dev/null || true
}

set_env() {  # set_env KEY VALUE: replace the line, or append it
  local key="$1" value="$2" tmp
  tmp="$(mktemp "${ENV_FILE}.XXXX")"
  grep -vE "^${key}=" "${ENV_FILE}" > "${tmp}" || true
  printf '%s=%s\n' "${key}" "${value}" >> "${tmp}"
  chmod --reference="${ENV_FILE}" "${tmp}"
  mv "${tmp}" "${ENV_FILE}"
}

cmd_check() {
  echo "App login now:      $(env_val MESIRI_POSTGRES__USER)"
  echo "Migration login:    $(env_val MESIRI_MIGRATION_POSTGRES__USER || true)"
  echo "Database:           ${DB} on ${HOST}:${PORT}"
  owner_psql -At <<SQL
SELECT 'Owner login is superuser: ' || rolsuper FROM pg_roles WHERE rolname = current_user;
SELECT 'Migration head: ' || version_num FROM alembic_version;
SELECT 'Tables with the tenant policy: ' || count(*) FROM pg_policies WHERE policyname = 'tenant_isolation';
SELECT '${APP_ROLE} exists: ' || EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${APP_ROLE}');
SELECT '${APP_ROLE} superuser/bypassrls: ' || rolsuper || '/' || rolbypassrls FROM pg_roles WHERE rolname = '${APP_ROLE}';
SQL
}

cmd_create() {  # cmd_create PASSWORD
  local password="$1" owner
  owner="$(owner_user)"
  [ "${owner}" != "${APP_ROLE}" ] || die "the owner login is ${APP_ROLE}; nothing to do"
  local head
  head="$(owner_psql -At -c 'SELECT version_num FROM alembic_version')"
  [[ "${head}" > "0483" ]] || die "migration head is ${head}; deploy 0484 (BE-03 step 2) first"
  # The password goes in on stdin, never on a command line (ps).
  { printf '\\set app_password %s\n' "${password}"; cat; } <<'SQL' |
SELECT format('CREATE ROLE %I LOGIN', :'app_role')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_role') \gexec
SELECT format('ALTER ROLE %I WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD %L',
              :'app_role', :'app_password') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', :'db', :'app_role') \gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'app_role') \gexec
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I', :'app_role') \gexec
SELECT format('GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO %I', :'app_role') \gexec
SELECT format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO %I', :'app_role') \gexec
-- Tables, sequences and functions later migrations create (as the owner).
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', :'owner', :'app_role') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I', :'owner', :'app_role') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO %I', :'owner', :'app_role') \gexec
SQL
    owner_psql -v app_role="${APP_ROLE}" -v owner="${owner}" -v db="${DB}"
  # The new login really connects and is not exempt from the policies.
  PGPASSWORD="${password}" psql -h "${HOST}" -p "${PORT}" -U "${APP_ROLE}" -d "${DB}" -X -At \
    -c "SELECT CASE WHEN rolsuper OR rolbypassrls THEN 'exempt' ELSE 'ok' END FROM pg_roles WHERE rolname = current_user" \
    | grep -qx ok || die "${APP_ROLE} can't connect or is exempt from row-level security"
  echo "${APP_ROLE} ready (owner: ${owner})."
}

cmd_switch() {
  [ -z "$(env_val MESIRI_MIGRATION_POSTGRES__USER)" ] || die "already switched (MESIRI_MIGRATION_POSTGRES__USER is set); use rollback first"
  local owner owner_password password backup
  owner="$(env_val MESIRI_POSTGRES__USER)"
  owner_password="$(env_val MESIRI_POSTGRES__PASSWORD)"
  [ -n "${owner}" ] && [ -n "${owner_password}" ] || die "MESIRI_POSTGRES__USER/PASSWORD not set in ${ENV_FILE}"
  password="$(openssl rand -hex 24)"

  cmd_create "${password}"

  backup="${ENV_FILE}.before-be03-$(date -u +%Y%m%dT%H%M%SZ)"
  cp -p "${ENV_FILE}" "${backup}"
  chmod 600 "${backup}"
  set_env MESIRI_MIGRATION_POSTGRES__USER "${owner}"
  set_env MESIRI_MIGRATION_POSTGRES__PASSWORD "${owner_password}"
  set_env MESIRI_POSTGRES__USER "${APP_ROLE}"
  set_env MESIRI_POSTGRES__PASSWORD "${password}"
  echo ".env updated (previous copy: ${backup})."

  restart
  if health; then
    echo "Switched: app and worker now log in as ${APP_ROLE}. /health OK."
    echo "Check: one WhatsApp test message, then the dashboard Today page."
  else
    echo "/health failed after the switch; rolling back." >&2
    cp -p "${backup}" "${ENV_FILE}"
    restart
    health && echo "Rolled back; /health OK on the previous login." >&2
    exit 1
  fi
}

cmd_rollback() {
  local backup
  backup="$(ls -1t ${BACKUP_GLOB} 2>/dev/null | head -1 || true)"
  [ -n "${backup}" ] || die "no ${BACKUP_GLOB} backup found"
  cp -p "${backup}" "${ENV_FILE}"
  restart
  health && echo "Rolled back to ${backup}; /health OK." || die "/health failed after rollback"
  echo "(${APP_ROLE} is left in place, unused.)"
}

case "${1:-}" in
  check) cmd_check ;;
  switch) cmd_switch ;;
  rollback) cmd_rollback ;;
  *) sed -n '2,18p' "$0"; exit 2 ;;
esac
