#!/usr/bin/env bash
# Read-only: the lines of one or more systemd services that match a pattern, for the last N hours (TM-41).
# Always ends with a count line, so "nothing" is never ambiguous: no matching lines vs. a quiet service vs. a
# service that is not running.
#
# Usage (on the VPS):  service_log.sh <hours> <max lines> <pattern> <unit> [unit ...]
set -uo pipefail
HOURS="$(printf '%s' "${1:-2}" | tr -dc 0-9)"; HOURS="${HOURS:-2}"
MAX="$(printf '%s' "${2:-300}" | tr -dc 0-9)"; MAX="${MAX:-300}"
PATTERN="${3:-.}"
shift 3 || true
UNITS=()
for u in "$@"; do UNITS+=(-u "$u"); done
ALL="$(journalctl "${UNITS[@]}" --since "${HOURS} hours ago" --no-pager -o short-iso 2>&1)"
TOTAL="$(printf '%s\n' "${ALL}" | grep -c . || true)"
HITS="$(printf '%s\n' "${ALL}" | grep -E "${PATTERN}" || true)"
COUNT="$(printf '%s\n' "${HITS}" | grep -c . || true)"
[ -n "${HITS}" ] && printf '%s\n' "${HITS}" | tail -"${MAX}"
echo
echo "== ${COUNT} matching line(s) of ${TOTAL} logged by $* in the last ${HOURS} h (showing the last ${MAX} at most)"
for u in "$@"; do
  printf '   %s: %s since %s\n' "$u" "$(systemctl is-active "$u" 2>/dev/null || echo unknown)" \
    "$(systemctl show -p ActiveEnterTimestamp --value "$u" 2>/dev/null || echo '?')"
done
