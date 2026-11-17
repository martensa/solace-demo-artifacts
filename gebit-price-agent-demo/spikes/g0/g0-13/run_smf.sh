#!/bin/bash
# G0-13 Teil B: solace-pubsubplus in python:3.13-slim (arm64 nativ, amd64
# emuliert) installieren und persistent auf VPN sam von solace-1 publizieren.
#
#   ./run_smf.sh run        Test-Queue anlegen, je Architektur 10 publizieren,
#                           Spool per SEMP zaehlen, konsumieren und pruefen
#   ./run_smf.sh cleanup    Test-Queue loeschen
#   ./run_smf.sh all        run + cleanup
#
# Zugangsdaten: SEMP-Admin und Client "default" aus der Terraform-Konfiguration
# von event-mesh-deployment (gelesen, nie ausgegeben). Legt nur die Queue
# gpos-g0-test auf VPN sam an.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TFV="$HERE/../../../../event-mesh-deployment/terraform/terraform.tfvars"
SEMP=http://127.0.0.1:8080/SEMP/v2
VPN=sam
QUEUE=gpos-g0-test
IMAGE=${IMAGE:-python:3.13-slim}
SDK=${SDK:-solace-pubsubplus==1.12.0}
export SOLACE_HOST=tcp://host.docker.internal:55557   # 55557 -> solace-1:55555
export SOLACE_VPN=$VPN
export SOLACE_USERNAME=default
SOLACE_PASSWORD=$(sed -n -E 's/^default_client_password[[:space:]]*=[[:space:]]*"(.*)"/\1/p' "$TFV")
export SOLACE_PASSWORD
SEMP_PW=$(sed -n -E 's/^solace_1_password[[:space:]]*=[[:space:]]*"(.*)"/\1/p' "$TFV")

semp() {   # semp METHOD PATH [JSON]
  if [ $# -ge 3 ]; then
    curl -s -u "admin:$SEMP_PW" -X "$1" -H 'Content-Type: application/json' "$SEMP$2" -d "$3"
  else
    curl -s -u "admin:$SEMP_PW" -X "$1" "$SEMP$2"
  fi
}
rc() { python3 -c 'import sys,json; d=json.load(sys.stdin); m=d.get("meta",{}); print(m.get("responseCode"), m.get("error",{}).get("description",""))'; }

queue_state() {
  semp GET "/monitor/msgVpns/$VPN/queues/$QUEUE?select=queueName,accessType,durable,ingressEnabled,egressEnabled,msgSpoolUsage,spooledMsgCount,spooledByteCount,bindSuccessCount,lastSpooledMsgId,highestAckedMsgId" |
    python3 -c 'import sys,json; print("   queue:", json.load(sys.stdin)["data"])'
  semp GET "/monitor/msgVpns/$VPN/queues/$QUEUE/msgs?count=100" | python3 -c '
import sys, json
d = json.load(sys.stdin)
ms = d.get("data", [])
print("   msgs on queue (SEMP /msgs):", len(ms))
if ms:
    print("   first msg fields:", {k: ms[0][k] for k in sorted(ms[0]) if k in ("msgId","publisherId","spooledTime","contentSize","attachmentSize","priority","undelivered","dmqEligible")})'
}

preflight() {
  echo "== Preflight: keine Abonnenten fuer gebit/, gpos/, showcase/ auf VPN $VPN"
  semp GET "/monitor/msgVpns/$VPN?select=msgVpnName,state,serviceSmfPlainTextEnabled,msgSpoolMsgCount" |
    python3 -c 'import sys,json; print("   vpn:", json.load(sys.stdin)["data"])'
  python3 - "$SEMP" "$VPN" <<'EOF'
import json, os, sys, urllib.parse, urllib.request, base64
semp, vpn = sys.argv[1], sys.argv[2]
tok = base64.b64encode(("admin:" + os.environ["SEMP_PW"]).encode()).decode()
def get(p):
    r = urllib.request.Request(semp + p, headers={"Authorization": "Basic " + tok})
    return json.load(urllib.request.urlopen(r))
hits = []
qs = [q["queueName"] for q in get(f"/config/msgVpns/{vpn}/queues?count=500&select=queueName")["data"]]
for q in qs:
    for s in get(f"/config/msgVpns/{vpn}/queues/{urllib.parse.quote(q, safe='')}/subscriptions?count=500")["data"]:
        if s["subscriptionTopic"].startswith(("gebit", "gpos", "showcase", ">", "*")):
            hits.append(("queue", q, s["subscriptionTopic"]))
cs = [c["clientName"] for c in get(f"/monitor/msgVpns/{vpn}/clients?count=500&select=clientName")["data"]]
for c in cs:
    for s in get(f"/monitor/msgVpns/{vpn}/clients/{urllib.parse.quote(c, safe='')}/subscriptions?count=1000")["data"]:
        if s["subscriptionTopic"].startswith(("gebit", "gpos", "showcase", ">", "*")):
            hits.append(("client", c, s["subscriptionTopic"]))
print(f"   queues={len(qs)} clients={len(cs)} matching_subscriptions={hits}")
sys.exit(1 if [h for h in hits if h[1] != "gpos-g0-test"] else 0)
EOF
}

client_stats() {   # SEMP v1 (nur lesen): Zaehler eines verbundenen Clients
  curl -s -u "admin:$SEMP_PW" http://127.0.0.1:8080/SEMP -d \
    "<rpc><show><client><name>$1</name><vpn-name>$VPN</vpn-name><stats/></client></show></rpc>" |
    grep -o -E '<(client-username|client-address|client-data-messages-received|client-persistent-messages-received|client-non-persistent-messages-received|client-direct-messages-received)>[^<]*' |
    sed -E 's/^<([a-z-]+)>/\1=/' | tr '\n' ' ' | sed 's/^/   SEMP v1 client stats: /' || true; echo
}

container() {   # container <platform> <args...>
  local plat=$1; shift
  docker run --rm --platform "linux/$plat" -e SOLACE_HOST -e SOLACE_VPN -e SOLACE_USERNAME \
    -e SOLACE_PASSWORD -v "$HERE/publisher:/app:ro" "$IMAGE" sh -c \
    "pip install -q --disable-pip-version-check --root-user-action=ignore '$SDK' >/dev/null && python -I /app/smf_publish_test.py $*"
}

do_run() {
  export SEMP_PW
  preflight
  echo "== Test-Queue $QUEUE auf VPN $VPN"
  semp POST "/config/msgVpns/$VPN/queues" "{\"queueName\":\"$QUEUE\",\"accessType\":\"exclusive\",\"permission\":\"consume\",\"ingressEnabled\":true,\"egressEnabled\":true,\"maxMsgSpoolUsage\":50}" | rc | sed 's/^/   create: /'
  for t in 'gebit/rp/>' 'gpos/v1/>'; do
    semp POST "/config/msgVpns/$VPN/queues/$QUEUE/subscriptions" "{\"subscriptionTopic\":\"$t\"}" | rc | sed "s|^|   subscribe $t: |"
  done
  queue_state
  for plat in arm64 amd64; do
    run=$(date +%H%M%S)-$plat
    echo "== Publish 10 aus $IMAGE linux/$plat ($SDK von PyPI), run $run"
    t0=$(date +%s)
    tmp=$(mktemp "${TMPDIR:-/tmp}/g0-13-pub.XXXXXX")
    container "$plat" publish --count 10 --run "$run" --hold 8 > "$tmp" 2>&1 &
    pid=$!
    for _ in $(seq 1 240); do grep -q publish_done "$tmp" && break; sleep 0.5; done
    client_stats "gpos-g0-13-pub-$run"
    wait "$pid"
    cat "$tmp"; rm -f "$tmp"
    echo "   Containerlauf $(( $(date +%s) - t0 )) s (inkl. pip install, 8 s Haltezeit)"
    queue_state
    echo "== Consume aus $QUEUE (linux/$plat)"
    container "$plat" consume --expect 10 --queue "$QUEUE" --run "$run"
    queue_state
  done
}

do_cleanup() {
  echo "== Test-Queue loeschen"
  semp DELETE "/config/msgVpns/$VPN/queues/$QUEUE" | rc
  semp GET "/config/msgVpns/$VPN/queues/$QUEUE" | rc
}

case "${1:-}" in
  run) do_run ;;
  cleanup) do_cleanup ;;
  all) do_run; do_cleanup ;;
  *) echo "usage: $0 run|cleanup|all" >&2; exit 2 ;;
esac
