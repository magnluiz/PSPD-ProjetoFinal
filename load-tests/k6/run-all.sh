#!/bin/bash
# Runs the k6 load test at 10, 50, 100, 500, and 1000 VUs, as required by
# the assignment (Section 3.b). Saves one JSON summary per stage under
# ./results/ for later analysis/plotting in the report.
#
# Usage:
#   BASE_URL=http://<gateway>:30080 KEYCLOAK_URL=http://localhost:8081 ./run-all.sh
#
# Set AUTH_MODE=insecure-dev only when the gateway is also running with
# AUTH_MODE=insecure-dev and you intentionally want header-based test identity.

# NOTE: intentionally NOT using `set -e` here. k6 exits non-zero when a
# threshold fails (e.g. error-rate or p95-latency threshold breached under
# heavy load), which is expected/interesting data for this assignment, not
# a reason to abort the whole run. Every stage should execute even if an
# earlier one "fails" its thresholds.
set -u
BASE_URL="${BASE_URL:-http://localhost:8080}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8081}"
AUTH_MODE="${AUTH_MODE:-keycloak}"
DURATION="${DURATION:-60s}"
mkdir -p results

FAILED_STAGES=()

for STAGE in 10 50 100 500 1000; do
  echo "=== Running k6 with $STAGE virtual users against $BASE_URL (auth=$AUTH_MODE) ==="

  set +e
  k6 run \
    -e BASE_URL="$BASE_URL" \
    -e KEYCLOAK_URL="$KEYCLOAK_URL" \
    -e AUTH_MODE="$AUTH_MODE" \
    -e STAGE="$STAGE" \
    -e DURATION="$DURATION" \
    --summary-export="results/k6-summary-${STAGE}vus.json" \
    load-test.js
  STATUS=$?
  set -e

  if [ $STATUS -ne 0 ]; then
    echo "!!! k6 exited with status $STATUS for $STAGE VUs (thresholds likely breached under load)."
    if [ -f "results/k6-summary-${STAGE}vus.json" ]; then
      echo "!!! Summary was still written to results/k6-summary-${STAGE}vus.json — continuing."
    else
      echo "!!! WARNING: no summary file was written for $STAGE VUs. This stage's data is missing."
    fi
    FAILED_STAGES+=("$STAGE")
  fi

  echo "--- sleeping 15s between stages to let the system settle ---"
  sleep 15
done

echo "All stages complete. Summaries saved in ./results/"
if [ ${#FAILED_STAGES[@]} -gt 0 ]; then
  echo "Stages that exited non-zero (check thresholds/logs): ${FAILED_STAGES[*]}"
fi
