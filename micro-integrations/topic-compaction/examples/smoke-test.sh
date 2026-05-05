#!/usr/bin/env bash
# =============================================================================
# End-to-end smoke test for the Topic Compaction MI.
#
# Non-interactive: every assertion drives an exit code, so the script
# is suitable for CI and `make smoke`.
#
# Modes:
#   ./examples/smoke-test.sh             - test against docker-compose MI
#                                          (defaults to localhost:18090)
#   ./examples/smoke-test.sh --k8s       - port-forward the K8s service
#                                          and test against that
#
# Required env (sourced from ../.env):
#   SOLACE_REST_HOST
#   SOLACE_REST_USER
#   SOLACE_REST_PASS
#   MI_PORT (optional, defaults to 18090)
#
# Optional, used when security.enabled=true:
#   MI_USER_NAME / MI_USER_PASSWORD
#   MI_ADMIN_NAME / MI_ADMIN_PASSWORD
# =============================================================================
set -euo pipefail

ENV_FILE="$(cd "$(dirname "$0")/.." && pwd)/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
else
  echo "ERROR: ${ENV_FILE} not found. Run: make env-init" >&2
  exit 1
fi

MODE="local"
[ "${1:-}" = "--k8s" ] && MODE="k8s"

BROKER_REST="${SOLACE_REST_HOST:-http://localhost:9000}"
BROKER_USER="${SOLACE_REST_USER:-default}"
BROKER_PASS="${SOLACE_REST_PASS:-default}"
MI_REST="http://localhost:${MI_PORT:-18090}"

# Auth header for MI REST (only used if creds are set in .env).
if [ -n "${MI_USER_NAME:-}" ] && [ -n "${MI_USER_PASSWORD:-}" ]; then
  MI_AUTH=(-u "$MI_USER_NAME:$MI_USER_PASSWORD")
else
  MI_AUTH=()
fi
if [ -n "${MI_ADMIN_NAME:-}" ] && [ -n "${MI_ADMIN_PASSWORD:-}" ]; then
  MI_ADMIN_AUTH=(-u "$MI_ADMIN_NAME:$MI_ADMIN_PASSWORD")
else
  MI_ADMIN_AUTH=()
fi

# K8s mode: port-forward the service, then proceed as for local.
PF_PID=""
cleanup() {
  if [ -n "$PF_PID" ] && kill -0 "$PF_PID" 2>/dev/null; then
    kill "$PF_PID" 2>/dev/null || true
    wait "$PF_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [ "$MODE" = "k8s" ]; then
  if ! command -v kubectl >/dev/null 2>&1; then
    echo "ERROR: kubectl is required for --k8s mode." >&2
    exit 2
  fi
  echo "Setting up port-forward to mi-solace-lab/topic-compaction-mi"
  kubectl -n mi-solace-lab port-forward \
      svc/topic-compaction-mi \
      "${MI_PORT:-18090}":8090 >/dev/null 2>&1 &
  PF_PID=$!
  sleep 3
fi

# -----------------------------------------------------------------------------
# Test framework
# -----------------------------------------------------------------------------
PASS=0
FAIL=0

check() {
  local label="$1"
  local expected="$2"
  local actual="$3"
  if [ "$actual" = "$expected" ]; then
    printf "  [PASS] %-50s expected=%s\n" "$label" "$expected"
    PASS=$((PASS + 1))
  else
    printf "  [FAIL] %-50s expected=%s got=%s\n" \
        "$label" "$expected" "$actual"
    FAIL=$((FAIL + 1))
  fi
}

http_code() {
  curl -s -o /dev/null -w "%{http_code}" "$@"
}

step() { printf "\n=== %s ===\n" "$*"; }

# -----------------------------------------------------------------------------
# 1. Sanity: MI is reachable and the bindings are UP.
# -----------------------------------------------------------------------------
step "1. Sanity"
check "health 200" "200" "$(http_code "${MI_REST}/actuator/health")"
check "prometheus 200" "200" \
    "$(http_code "${MI_REST}/actuator/prometheus")"

# -----------------------------------------------------------------------------
# 2. Compaction round trip - publish 3 messages, verify they arrive
#    in the KV store with last-wins semantics.
# -----------------------------------------------------------------------------
step "2. Compaction round trip"
TS=$(date +%s)
KEY_PREFIX="orders/smoke/${TS}"
for k in A B C; do
  curl -fsS -u "${BROKER_USER}:${BROKER_PASS}" \
      -X POST "${BROKER_REST}/TOPIC/${KEY_PREFIX}/${k}" \
      -H 'Content-Type: application/json' \
      -d "{\"orderId\":\"${k}\",\"ts\":${TS}}" \
      > /dev/null
done
sleep 2

# Update key A so we can verify last-wins.
curl -fsS -u "${BROKER_USER}:${BROKER_PASS}" \
    -X POST "${BROKER_REST}/TOPIC/${KEY_PREFIX}/A" \
    -H 'Content-Type: application/json' \
    -d "{\"orderId\":\"A\",\"ts\":${TS},\"updated\":true}" \
    > /dev/null
sleep 2

LIST_JSON=$(curl -fsS "${MI_AUTH[@]}" \
    "${MI_REST}/api/v1/kv?prefix=${KEY_PREFIX}/")
COUNT=$(printf '%s' "$LIST_JSON" \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["count"])')
check "kv count after 3+1 publishes" "3" "$COUNT"

GET_BODY=$(curl -fsS "${MI_AUTH[@]}" \
    "${MI_REST}/api/v1/kv/${KEY_PREFIX}/A")
case "$GET_BODY" in
  *'"updated":true'*)
    check "last-wins on key A" "true" "true" ;;
  *)
    check "last-wins on key A" "true" "false (body=$GET_BODY)" ;;
esac

# -----------------------------------------------------------------------------
# 3. Replay command - verify metrics increment.
# -----------------------------------------------------------------------------
step "3. Replay"
REPLAYS_BEFORE=$(curl -fsS "${MI_REST}/actuator/prometheus" \
    | awk '/^topic_compaction_replays_total/ \
        {gsub(/[^0-9.]/, "", $NF); print $NF; exit}')
REPLAYS_BEFORE=${REPLAYS_BEFORE:-0}

curl -fsS -u "${BROKER_USER}:${BROKER_PASS}" \
    -X POST "${BROKER_REST}/TOPIC/compacted/command/replay" \
    -H 'Content-Type: application/json' \
    -d "{\"command\":\"REPLAY\",\"key\":\"${KEY_PREFIX}/A\"}" \
    > /dev/null
sleep 3

REPLAYS_AFTER=$(curl -fsS "${MI_REST}/actuator/prometheus" \
    | awk '/^topic_compaction_replays_total/ \
        {gsub(/[^0-9.]/, "", $NF); print $NF; exit}')
REPLAYS_AFTER=${REPLAYS_AFTER:-0}

INCREMENTED="false"
python3 -c "import sys; sys.exit(0 if float(\"$REPLAYS_AFTER\") > float(\"$REPLAYS_BEFORE\") else 1)" \
    && INCREMENTED="true"
check "replay counter incremented (was=$REPLAYS_BEFORE now=$REPLAYS_AFTER)" \
    "true" "$INCREMENTED"

# -----------------------------------------------------------------------------
# 4. Bulk replay - publish a command, verify the summary lands.
#    For non-interactive smoke we only assert the command was accepted
#    (the result event itself requires a Solace consumer subscription).
# -----------------------------------------------------------------------------
step "4. Bulk replay command accepted"
BULK_HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
    -u "${BROKER_USER}:${BROKER_PASS}" \
    -X POST "${BROKER_REST}/TOPIC/compacted/command/bulk-replay" \
    -H 'Content-Type: application/json' \
    -d "{\"command\":\"BULK_REPLAY\",\"pattern\":\"${KEY_PREFIX}/*\"}")
check "bulk-replay command published" "200" "$BULK_HTTP"

# -----------------------------------------------------------------------------
# 5. Tombstone via REST + verify - exercises the slash-encoding path.
# -----------------------------------------------------------------------------
step "5. Tombstone via REST"
DEL_AUTH=("${MI_ADMIN_AUTH[@]:-${MI_AUTH[@]}}")
DEL_HTTP=$(http_code "${DEL_AUTH[@]}" -X DELETE \
    "${MI_REST}/api/v1/kv/${KEY_PREFIX}/C")
check "delete C returns 204" "204" "$DEL_HTTP"

GET_AFTER_DEL=$(http_code "${MI_AUTH[@]}" \
    "${MI_REST}/api/v1/kv/${KEY_PREFIX}/C")
check "C is gone (404)" "404" "$GET_AFTER_DEL"

# -----------------------------------------------------------------------------
# 6. Backup endpoint (admin-only) - exercises the streaming response.
#    Skipped when admin credentials are not in .env.
# -----------------------------------------------------------------------------
if [ ${#MI_ADMIN_AUTH[@]} -gt 0 ]; then
  step "6. Backup admin endpoint"
  BACKUP_FILE=$(mktemp -t topic-compaction-smoke-backup.XXXXXX.ndjson)
  trap 'rm -f "$BACKUP_FILE"; cleanup' EXIT
  BACKUP_HTTP=$(curl -s -o "$BACKUP_FILE" -w "%{http_code}" \
      "${MI_ADMIN_AUTH[@]}" \
      -X POST "${MI_REST}/api/v1/admin/backup")
  check "backup returns 200" "200" "$BACKUP_HTTP"
  HEADER_LINE=$(head -1 "$BACKUP_FILE")
  case "$HEADER_LINE" in
    *'"version":1'*)
      check "backup header v1" "true" "true" ;;
    *)
      check "backup header v1" "true" \
          "false (header=$HEADER_LINE)" ;;
  esac
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
step "Result"
echo "  passed: $PASS"
echo "  failed: $FAIL"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
