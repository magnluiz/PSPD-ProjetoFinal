#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

STAGE="${STAGE:-10}"
DURATION="${DURATION:-15s}"
RAMP_UP="${RAMP_UP:-5s}"
RAMP_DOWN="${RAMP_DOWN:-5s}"
P95_THRESHOLD_MS="${P95_THRESHOLD_MS:-10000}"
FAIL_RATE_THRESHOLD="${FAIL_RATE_THRESHOLD:-0.05}"
SETUP_TIMEOUT="${SETUP_TIMEOUT:-180s}"

if [[ -z "${TEST_PASSWORD:-}" ]]; then
  TEST_PASSWORD="$(awk -F= '/TEST_PASSWORD=/{gsub(/[ `]/, "", $2); print $2; exit}' "$PROJECT_ROOT/README.md")"
fi

if [[ -z "$TEST_PASSWORD" ]]; then
  echo "Erro: TEST_PASSWORD não foi informada nem encontrada no README.md." >&2
  exit 1
fi

mkdir -p "$SCRIPT_DIR/results"

echo "Executando teste: ${STAGE} VUs, duração ${DURATION}, ramp-up ${RAMP_UP}, ramp-down ${RAMP_DOWN}"

BASE_URL="${BASE_URL:-https://kiriland.unb.br/grupo6}" \
KEYCLOAK_URL="${KEYCLOAK_URL:-https://kiriland.unb.br/keycloak}" \
KEYCLOAK_REALM="${KEYCLOAK_REALM:-grupo06}" \
CLIENT_ID="${CLIENT_ID:-admin-cli}" \
TEST_PASSWORD="$TEST_PASSWORD" \
STAGE="$STAGE" \
DURATION="$DURATION" \
RAMP_UP="$RAMP_UP" \
RAMP_DOWN="$RAMP_DOWN" \
P95_THRESHOLD_MS="$P95_THRESHOLD_MS" \
FAIL_RATE_THRESHOLD="$FAIL_RATE_THRESHOLD" \
SETUP_TIMEOUT="$SETUP_TIMEOUT" \
k6 run \
  --summary-export="$SCRIPT_DIR/results/grafana-${STAGE}vus.json" \
  "$SCRIPT_DIR/load-test.js"
