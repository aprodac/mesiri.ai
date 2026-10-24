#!/usr/bin/env bash
# WA-10: switch Meta-approved WhatsApp templates on, by listing them in
# WHATSAPP_APPROVED_TEMPLATES (docs/ops/whatsapp-templates.md). Prints only
# template names and MESIRI_LOGIN_CODE_SENDER, never another setting.
#
# Usage (on the VPS, as root):
#   bash whatsapp_templates.sh check                       # read-only
#   bash whatsapp_templates.sh add mesiri_login_code[,..]  # add, restart, health check
#
# `add` only accepts names declared in channel/whatsapp/templates.py, backs up
# .env first, and puts the backup back if /health fails after the restart.
set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/mesiri/.env}"
KEY="WHATSAPP_APPROVED_TEMPLATES"
KNOWN="mesiri_dpr_delivery mesiri_dpr_optin mesiri_join_request mesiri_login_code mesiri_ops_alert mesiri_site_day_review mesiri_site_no_update mesiri_trial_ending"

env_val() { { grep -E "^$1=" "${ENV_FILE}" 2>/dev/null || true; } | tail -1 | cut -d= -f2- | tr -d '"'"'"' \r'; }
die() { echo "ERROR: $*" >&2; exit 1; }

[ -f "${ENV_FILE}" ] || die "${ENV_FILE} not found"
APP_PORT="$(env_val MESIRI_APP_PORT)"; APP_PORT="${APP_PORT:-8000}"

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
  local sender
  sender="$(env_val MESIRI_LOGIN_CODE_SENDER)"
  echo "${KEY}=$(env_val "${KEY}")"
  echo "MESIRI_LOGIN_CODE_SENDER=${sender:-(unset: whatsapp)}"
  [ "${sender}" != "dev" ] || echo "WARNING: MESIRI_LOGIN_CODE_SENDER=dev shows codes on the page; never on a live server"
  echo "mesiri: $(systemctl is-active mesiri 2>/dev/null || true), mesiri-worker: $(systemctl is-active mesiri-worker 2>/dev/null || true)"
}

cmd_add() {  # cmd_add name[,name...]
  local requested="$1" current merged name backup
  [ -n "${requested}" ] || die "no template names given"
  for name in ${requested//,/ }; do
    [[ " ${KNOWN} " == *" ${name} "* ]] || die "unknown template: ${name}"
  done
  current="$(env_val "${KEY}")"
  merged="$(printf '%s\n' ${current//,/ } ${requested//,/ } | awk 'NF && !seen[$0]++' | paste -sd, -)"
  if [ "${merged}" = "${current}" ]; then
    echo "Already listed; nothing to change."
    cmd_check
    return 0
  fi

  backup="${ENV_FILE}.before-templates-$(date -u +%Y%m%dT%H%M%SZ)"
  cp -p "${ENV_FILE}" "${backup}"
  chmod 600 "${backup}"
  set_env "${KEY}" "${merged}"
  echo "${KEY}: '${current}' -> '${merged}' (previous .env: ${backup})"

  restart
  if health; then
    echo "Restarted mesiri and mesiri-worker; /health OK."
    cmd_check
  else
    echo "/health failed after the restart; putting the previous .env back." >&2
    cp -p "${backup}" "${ENV_FILE}"
    restart
    health && echo "Rolled back; /health OK." >&2
    exit 1
  fi
}

case "${1:-}" in
  check) cmd_check ;;
  add) cmd_add "${2:-}" ;;
  *) sed -n '2,12p' "$0"; exit 2 ;;
esac
