#!/usr/bin/env bash
# Runs the k6 load test at 10, 50, 100, 500, and 1000 VUs, as required by
# the assignment (Section 3.b). Saves one JSON summary per stage under
# ./results/ for later analysis/plotting in the report.
#
# Usage (pode ser executado a partir de qualquer diretório):
#   ./load-tests/k6/run-all.sh
#   DURATION=30s ./load-tests/k6/run-all.sh
#
# Set AUTH_MODE=insecure-dev only when the gateway is also running with
# AUTH_MODE=insecure-dev and you intentionally want header-based test identity.

# NOTE: intentionally NOT using `set -e` here. k6 exits non-zero when a
# threshold fails (e.g. error-rate or p95-latency threshold breached under
# heavy load), which is expected/interesting data for this assignment, not
# a reason to abort the whole run. Every stage should execute even if an
# earlier one "fails" its thresholds.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

BASE_URL="${BASE_URL:-https://kiriland.unb.br/grupo6}"
KEYCLOAK_URL="${KEYCLOAK_URL:-https://kiriland.unb.br/keycloak}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-grupo06}"
CLIENT_ID="${CLIENT_ID:-admin-cli}"
AUTH_MODE="${AUTH_MODE:-keycloak}"
if [ -z "${TEST_PASSWORD:-}" ]; then
  TEST_PASSWORD="$(awk -F= '/TEST_PASSWORD=/{gsub(/[ `]/, "", $2); print $2; exit}' "$PROJECT_ROOT/README.md")"
fi
if [ -z "$TEST_PASSWORD" ]; then
  echo "Erro: TEST_PASSWORD não foi informada nem encontrada no README.md." >&2
  exit 1
fi
DURATION="${DURATION:-60s}"
RAMP_UP="${RAMP_UP:-15s}"
RAMP_DOWN="${RAMP_DOWN:-10s}"
P95_THRESHOLD_MS="${P95_THRESHOLD_MS:-10000}"
FAIL_RATE_THRESHOLD="${FAIL_RATE_THRESHOLD:-0.05}"
SETUP_TIMEOUT="${SETUP_TIMEOUT:-180s}"
SETTLE_SECONDS="${SETTLE_SECONDS:-15}"
RESULTS_DIR="$SCRIPT_DIR/results"
mkdir -p "$RESULTS_DIR"

FAILED_STAGES=()

for STAGE in 10 50 100 500 1000; do
  echo "=== Running k6 with $STAGE virtual users against $BASE_URL (auth=$AUTH_MODE) ==="

  set +e
  k6 run \
    -e BASE_URL="$BASE_URL" \
    -e KEYCLOAK_URL="$KEYCLOAK_URL" \
    -e KEYCLOAK_REALM="$KEYCLOAK_REALM" \
    -e CLIENT_ID="$CLIENT_ID" \
    -e AUTH_MODE="$AUTH_MODE" \
    -e TEST_PASSWORD="$TEST_PASSWORD" \
    -e STAGE="$STAGE" \
    -e DURATION="$DURATION" \
    -e RAMP_UP="$RAMP_UP" \
    -e RAMP_DOWN="$RAMP_DOWN" \
    -e P95_THRESHOLD_MS="$P95_THRESHOLD_MS" \
    -e FAIL_RATE_THRESHOLD="$FAIL_RATE_THRESHOLD" \
    -e SETUP_TIMEOUT="$SETUP_TIMEOUT" \
    --summary-export="$RESULTS_DIR/k6-summary-${STAGE}vus.json" \
    "$SCRIPT_DIR/load-test.js"
  STATUS=$?
  set -e

  if [ $STATUS -ne 0 ]; then
    echo "!!! k6 exited with status $STATUS for $STAGE VUs (thresholds likely breached under load)."
    if [ -f "$RESULTS_DIR/k6-summary-${STAGE}vus.json" ]; then
      echo "!!! Summary was still written to $RESULTS_DIR/k6-summary-${STAGE}vus.json — continuing."
    else
      echo "!!! WARNING: no summary file was written for $STAGE VUs. This stage's data is missing."
    fi
    FAILED_STAGES+=("$STAGE")
  fi

  echo "--- sleeping ${SETTLE_SECONDS}s between stages to let the system settle ---"
  sleep "$SETTLE_SECONDS"
done

echo "All stages complete. Summaries saved in ./results/"
if [ ${#FAILED_STAGES[@]} -gt 0 ]; then
  echo "Stages that exited non-zero (check thresholds/logs): ${FAILED_STAGES[*]}"
fi
