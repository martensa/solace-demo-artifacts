#!/bin/sh
# Provision queues + topic subscriptions on the Solace broker for the Topic
# Compaction MI. Idempotent: re-running is safe (creates 400 if already exists,
# we tolerate that).
set -e

BROKER="${SOLACE_HOST:-solace-broker}:8080"
AUTH="admin:admin"
HDR="Content-Type: application/json"

create_queue() {
  local name="$1"
  echo "Creating queue: ${name}"
  http_code=$(curl -s -o /tmp/r -w "%{http_code}" -u "$AUTH" \
    -X POST "http://${BROKER}/SEMP/v2/config/msgVpns/default/queues" \
    -H "$HDR" \
    -d "{\"queueName\":\"${name}\",\"egressEnabled\":true,\"ingressEnabled\":true,\"owner\":\"default\",\"permission\":\"consume\",\"accessType\":\"non-exclusive\"}")
  if [ "$http_code" != "200" ] && [ "$http_code" != "400" ]; then
    echo "  unexpected HTTP $http_code on queue create:"
    cat /tmp/r
    exit 1
  fi
}

add_subscription() {
  local queue="$1"
  local topic="$2"
  echo "Subscribing queue ${queue} to topic ${topic}"
  http_code=$(curl -s -o /tmp/r -w "%{http_code}" -u "$AUTH" \
    -X POST "http://${BROKER}/SEMP/v2/config/msgVpns/default/queues/${queue}/subscriptions" \
    -H "$HDR" \
    -d "{\"subscriptionTopic\":\"${topic}\"}")
  if [ "$http_code" != "200" ] && [ "$http_code" != "400" ]; then
    echo "  unexpected HTTP $http_code on subscription create:"
    cat /tmp/r
    exit 1
  fi
}

echo "Waiting 5s for SEMP to settle..."
sleep 5

create_queue "compaction.data"
add_subscription "compaction.data" "orders/>"

create_queue "compaction.commands"
add_subscription "compaction.commands" "compacted/command/>"

create_queue "compaction.lookup"
add_subscription "compaction.lookup" "compacted/lookup/>"

echo "Queue setup complete."
