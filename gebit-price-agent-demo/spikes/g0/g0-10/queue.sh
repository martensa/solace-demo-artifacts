#!/bin/bash
set -uo pipefail
# G0-10: own queue gpos-spike-p10-q on VPN default (solace-1, SEMP v2
# localhost:8080, admin password read at runtime from the event-mesh
# terraform.tfvars, never printed or stored).
#   ./queue.sh create | show | sam | egress on|off | delete
#   ./queue.sh semp GET|PATCH|POST|DELETE <path> [json]   (raw)
TF="$(cd "$(dirname "$0")" && pwd)/../../../../event-mesh-deployment/terraform/terraform.tfvars"
P=$(grep '^solace_1_password' "$TF" | sed -E 's/^[^=]*=[[:space:]]*"?([^"]*)"?.*/\1/')
Q=gpos-spike-p10-q
TOPIC='gpos/spike/p10/own/>'
semp() {
  local m=$1 u=$2 b=${3:-}
  if [ -n "$b" ]; then
    curl -s -u "admin:$P" -X "$m" -H 'Content-Type: application/json' \
      -d "$b" "http://localhost:8080/SEMP/v2/$u"
  else
    curl -s -u "admin:$P" -X "$m" "http://localhost:8080/SEMP/v2/$u"
  fi
}
rc() { python3 -c 'import json,sys;m=json.load(sys.stdin)["meta"];print(m["responseCode"],m.get("error",{}).get("description",""))'; }
case "${1:-show}" in
  create)
    semp POST "config/msgVpns/default/queues" "{\"queueName\":\"$Q\",
      \"accessType\":\"exclusive\",\"permission\":\"consume\",
      \"ingressEnabled\":true,\"egressEnabled\":true,
      \"respectTtlEnabled\":true,\"maxTtl\":20,\"maxRedeliveryCount\":1,
      \"maxMsgSpoolUsage\":50}" | rc
    semp POST "config/msgVpns/default/queues/$Q/subscriptions" \
      "{\"subscriptionTopic\":\"$TOPIC\"}" | rc ;;
  show)
    semp GET "monitor/msgVpns/default/queues/$Q" | python3 -c '
import json,sys; d=json.load(sys.stdin)
if d["meta"]["responseCode"]!=200: print(d["meta"]); sys.exit()
q=d["data"]; ks=["queueName","owner","permission","accessType","durable","respectTtlEnabled",
"maxTtl","maxRedeliveryCount","maxMsgSpoolUsage","egressEnabled","spooledMsgCount",
"maxTtlExpiredDiscardedMsgCount","maxTtlExpiredToDmqMsgCount","maxRedeliveryExceededDiscardedMsgCount","redeliveredMsgCount"]
print({k:q.get(k) for k in ks})'
    semp GET "monitor/msgVpns/default/queues/$Q/msgs?count=100" | python3 -c '
import json,sys; d=json.load(sys.stdin); print("msgs on queue:", len(d.get("data",[])))'
    semp GET "monitor/msgVpns/default/queues/$Q/txFlows" | python3 -c '
import json,sys; d=json.load(sys.stdin); print("txFlows:", [(f.get("clientName"),f.get("flowId")) for f in d.get("data",[])])' ;;
  sam)
    semp GET "monitor/msgVpns/default/queues?count=100&where=queueName==sam-solace-lab*" | python3 -c '
import json,sys; d=json.load(sys.stdin)
for q in d.get("data",[]):
  print({k:q.get(k) for k in ["queueName","owner","accessType","durable","respectTtlEnabled","maxTtl","maxRedeliveryCount","maxMsgSpoolUsage","spooledMsgCount"]})' ;;
  egress)
    v=false; [ "${2:-}" = on ] && v=true
    semp PATCH "config/msgVpns/default/queues/$Q" "{\"egressEnabled\":$v}" | rc ;;
  delete)
    semp DELETE "config/msgVpns/default/queues/$Q" | rc ;;
  semp) shift; semp "$@" ;;
esac
