#!/usr/bin/env bash
# =============================================================================
# Provision queues + subscriptions for the Topic Compaction MI.
#
# Reads broker credentials from ../.env (or env vars if already set). Works
# against ANY Solace broker reachable via SEMP HTTP/HTTPS (Solace Cloud,
# agent-mesh-deployment, or local). Idempotent: 400-on-already-exists is OK.
#
# Usage:
#   cp ../.env.example ../.env && $EDITOR ../.env
#   ./init-queues.sh
#
# Env vars (overridable inline):
#   SEMP_URL    full SEMP base URL, e.g. https://mr-connection-XXX.messaging.solace.cloud:943
#   SEMP_USER   SEMP admin user (default: $SOLACE_USERNAME)
#   SEMP_PASS   SEMP admin password (default: $SOLACE_PASSWORD)
#   SEMP_VPN    VPN name (default: $SOLACE_VPN)
#   DATA_TOPIC  Subscription pattern for the compaction.data queue (default: orders/>)
# =============================================================================
set -euo pipefail

ENV_FILE="$(cd "$(dirname "$0")/.." && pwd)/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

SEMP_URL="${SEMP_URL:-}"
SEMP_USER="${SEMP_USER:-${SOLACE_USERNAME:-admin}}"
SEMP_PASS="${SEMP_PASS:-${SOLACE_PASSWORD:-admin}}"
SEMP_VPN="${SEMP_VPN:-${SOLACE_VPN:-default}}"
DATA_TOPIC="${DATA_TOPIC:-orders/>}"

if [ -z "$SEMP_URL" ]; then
  cat <<'EOF'
ERROR: SEMP_URL is not set.

  For Solace Cloud: see your Service's Connect tab -> "Solace Element
  Management Protocol (SEMP)" host. Looks like:
    SEMP_URL=https://mr-connection-XXXXXXXX.messaging.solace.cloud:943

  For a local broker (agent-mesh-deployment etc.):
    SEMP_URL=http://localhost:8080

Set it in ../.env or inline before re-running.
EOF
  exit 1
fi

echo "Provisioning against ${SEMP_URL}"
echo "  vpn=${SEMP_VPN}, data-subscription=${DATA_TOPIC}"

call() {
  local method="$1"
  local path="$2"
  local body="$3"
  local code
  code=$(curl -sk -o /tmp/semp.out -w "%{http_code}" \
    -u "${SEMP_USER}:${SEMP_PASS}" \
    -X "${method}" "${SEMP_URL}${path}" \
    -H 'Content-Type: application/json' \
    -d "${body}")
  if [ "$code" != "200" ] && [ "$code" != "400" ]; then
    echo "  ${method} ${path} -> HTTP ${code}:"
    cat /tmp/semp.out
    return 1
  fi
}

create_queue() {
  local name="$1"
  echo "Creating queue: ${name}"
  call POST "/SEMP/v2/config/msgVpns/${SEMP_VPN}/queues" \
    "{\"queueName\":\"${name}\",\"egressEnabled\":true,\"ingressEnabled\":true,\"permission\":\"consume\",\"accessType\":\"non-exclusive\"}"
}

add_subscription() {
  local queue="$1"
  local topic="$2"
  echo "Subscribing queue ${queue} -> ${topic}"
  call POST "/SEMP/v2/config/msgVpns/${SEMP_VPN}/queues/${queue}/subscriptions" \
    "{\"subscriptionTopic\":\"${topic}\"}"
}

create_queue "compaction.data"
add_subscription "compaction.data" "${DATA_TOPIC}"

create_queue "compaction.commands"
add_subscription "compaction.commands" "compacted/command/>"

create_queue "compaction.lookup"
add_subscription "compaction.lookup" "compacted/lookup/>"

echo "Done."
