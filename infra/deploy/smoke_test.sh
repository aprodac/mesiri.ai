#!/usr/bin/env bash
# Post-deploy smoke test: is the deployed WhatsApp assistant actually working,
# not just running?
#
# The deploy's existing health check only asks "does /health/live answer?".
# That passed on the deploy where the worker was missing and every WhatsApp
# message silently vanished (see deploy.yml, step 1b). This checks the parts
# a customer depends on:
#
#   1. the API answers                              (/health/live)
#   2. the commit we just deployed is the one live  (/health build sha)
#   3. photos go to real storage, not memory         (/health media_storage)
#   4. Meta can reach the webhook                    (verification handshake)
#   5. the queue worker is alive and ticking         (ARQ health-check key)
#
# Usage (on the VPS, after services restart):
#   infra/deploy/smoke_test.sh <expected-short-sha> [base-url]
#
# Exits non-zero on the first failure, printing what failed. Reads only; it
# sends no WhatsApp message and writes nothing.
set -uo pipefail

EXPECTED_SHA="${1:?usage: smoke_test.sh <expected-short-sha> [base-url]}"
BASE_URL="${2:-http://127.0.0.1:8000}"
ENV_FILE="${ENV_FILE:-/opt/mesiri/.env}"
QUEUE_HEALTH_KEY="${QUEUE_HEALTH_KEY:-mesiri:whatsapp:ingress:health-check}"

FAILED=0
pass() { echo "  ✓ $1"; }
fail() { echo "  ✗ $1"; FAILED=1; }

env_value() {
  # Last assignment wins, like the shell would; quotes and CR stripped.
  grep -E "^$1=" "${ENV_FILE}" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' \r'
}

echo "── Smoke test against ${BASE_URL} (expecting build ${EXPECTED_SHA}) ──"

# 1. Liveness
if curl -sf --max-time 5 "${BASE_URL}/health/live" > /dev/null; then
  pass "API is up"
else
  fail "API did not answer /health/live"
fi

# 2 + 3. Build and storage, from one /health call
HEALTH_JSON="$(curl -sf --max-time 5 "${BASE_URL}/health" || true)"
LIVE_SHA="$(printf '%s' "${HEALTH_JSON}" | sed -n 's/.*"build" *: *"\([^"]*\)".*/\1/p')"
STORAGE="$(printf '%s' "${HEALTH_JSON}" | sed -n 's/.*"media_storage" *: *"\([^"]*\)".*/\1/p')"
if [ -n "${LIVE_SHA}" ] && { [[ "${EXPECTED_SHA}" == "${LIVE_SHA}"* ]] || [[ "${LIVE_SHA}" == "${EXPECTED_SHA}"* ]]; }; then
  pass "running build ${LIVE_SHA}"
else
  fail "running build is '${LIVE_SHA:-unknown}', expected ${EXPECTED_SHA}"
fi
if [ -n "${STORAGE}" ] && [ "${STORAGE}" != "fake" ]; then
  pass "media storage: ${STORAGE}"
else
  fail "media storage is '${STORAGE:-unknown}' (photos would be lost)"
fi

# 4. Webhook verification handshake, exactly as Meta performs it
VERIFY_TOKEN="$(env_value WHATSAPP_VERIFY_TOKEN)"
[ -z "${VERIFY_TOKEN}" ] && VERIFY_TOKEN="$(env_value MESIRI_WHATSAPP__VERIFY_TOKEN)"
if [ -z "${VERIFY_TOKEN}" ]; then
  fail "no WhatsApp verify token found in ${ENV_FILE}"
else
  CHALLENGE="smoke-$(date +%s)"
  ECHO="$(curl -sf --max-time 5 -G "${BASE_URL}/webhook" \
    --data-urlencode "hub.mode=subscribe" \
    --data-urlencode "hub.verify_token=${VERIFY_TOKEN}" \
    --data-urlencode "hub.challenge=${CHALLENGE}" || true)"
  if [ "${ECHO}" = "${CHALLENGE}" ]; then
    pass "webhook verification handshake"
  else
    fail "webhook did not echo the challenge"
  fi
fi

# 5. Worker liveness: ARQ refreshes this key every 30 s and Redis expires it
# when the worker stops, so present == alive within the last interval. A
# freshly restarted worker may not have written it yet, so allow up to ~45 s.
if command -v redis-cli > /dev/null; then
  WORKER_OK=false
  for _ in $(seq 1 15); do
    if [ -n "$(redis-cli --raw GET "${QUEUE_HEALTH_KEY}" 2>/dev/null)" ]; then
      WORKER_OK=true
      break
    fi
    sleep 3
  done
  if [ "${WORKER_OK}" = "true" ]; then
    pass "queue worker is alive"
  else
    fail "queue worker health key missing after 45 s (worker down?)"
  fi
else
  fail "redis-cli not available to check the worker"
fi

if [ "${FAILED}" -ne 0 ]; then
  echo "✗ Smoke test FAILED"
  exit 1
fi
echo "✓ Smoke test passed"
