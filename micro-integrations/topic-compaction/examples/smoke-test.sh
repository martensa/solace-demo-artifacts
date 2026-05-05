#!/usr/bin/env bash
# =============================================================================
# End-to-end smoke test for the Topic Compaction MI.
#
# Loads ../.env for broker REST + MI port settings. Works against any Solace
# broker (Solace Cloud, agent-mesh-deployment, local). Run with:
#
#   ./examples/smoke-test.sh
#
# Required env vars (sourced from ../.env):
#   SOLACE_REST_HOST   e.g. http://mr-connection-XXX.messaging.solace.cloud:9000
#   SOLACE_REST_USER
#   SOLACE_REST_PASS
#   MI_PORT            host port where the MI is exposed (default: 18090)
# =============================================================================
set -euo pipefail

ENV_FILE="$(cd "$(dirname "$0")/.." && pwd)/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
else
  echo "ERROR: ${ENV_FILE} not found. Run: make env-init"
  exit 1
fi

BROKER_REST="${SOLACE_REST_HOST:-http://localhost:9000}"
BROKER_USER="${SOLACE_REST_USER:-default}"
BROKER_PASS="${SOLACE_REST_PASS:-default}"
MI_REST="http://localhost:${MI_PORT:-18090}"

step() { echo; echo "===== $* ====="; }

step "Sanity: MI health"
curl -fsS "${MI_REST}/actuator/health" | head -c 200; echo

step "1. Publish 3 messages on different topics"
for k in A B C; do
  curl -fsS -u "${BROKER_USER}:${BROKER_PASS}" \
    -X POST "${BROKER_REST}/TOPIC/orders/created/${k}" \
    -H 'Content-Type: application/json' \
    -d "{\"orderId\":\"${k}\",\"amount\":${RANDOM}}"
done
echo "Published 3 messages."
sleep 2

step "2. Verify the KV store contains them"
curl -fsS "${MI_REST}/api/v1/kv?prefix=orders/"; echo

step "3. Update orders/created/A and verify last-wins"
curl -fsS -u "${BROKER_USER}:${BROKER_PASS}" \
  -X POST "${BROKER_REST}/TOPIC/orders/created/A" \
  -H 'Content-Type: application/json' \
  -d '{"orderId":"A","amount":99,"updated":true}'
sleep 2
echo "Count should still be 3 (replace, not append):"
curl -fsS "${MI_REST}/api/v1/kv?prefix=orders/"; echo

step "4. Trigger replay via command event"
echo "Subscribe to orders/created/A/compacted in another terminal first:"
echo "  curl -fsSN -u ${BROKER_USER}:${BROKER_PASS} '${BROKER_REST}/SUBSCRIBE/orders/created/A/compacted'"
echo
read -p "Press ENTER once subscribed (or Ctrl-C to skip)..."

curl -fsS -u "${BROKER_USER}:${BROKER_PASS}" \
  -X POST "${BROKER_REST}/TOPIC/compacted/command/replay" \
  -H 'Content-Type: application/json' \
  -d '{"command":"REPLAY","key":"orders/created/A"}'
echo
echo "Replay command sent. Subscriber should now see the latest payload"
echo "for orders/created/A on topic orders/created/A/compacted."
sleep 2

step "5. Tombstone via REST"
curl -fsS -X DELETE "${MI_REST}/api/v1/kv/orders%2Fcreated%2FC" || true
echo

echo
echo "Smoke test complete."
