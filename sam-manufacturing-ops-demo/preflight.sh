#!/bin/bash
set -uo pipefail

# =============================================================
# preflight.sh -- automated Appendix A checklist (talk-track.md)
# with AUTO-FIX. Run ~15 minutes before going live; after a
# clean run the environment is validated and demo-ready.
#
# Every check that fails triggers its fix and re-checks:
#   platform resources missing   -> ./install.sh (idempotent)
#   Shop Floor Analyst present   -> deleted (live Builder beat)
#   postgres data                -> postgres/seed.sh + spot-check
#   wrong/empty mongo            -> compose down -v && up (reseed)
#   other demo's mongo running   -> stopped (port 27017 rule)
#   broker WS down               -> docker start solace-1/2, retry
#   dashboard ConfigMap missing  -> kubectl apply
#   evals without completed runs -> sam eval run (the 15-min part)
# Not auto-fixable (reported with instructions): sam login
# (browser flow), unhealthy cluster pods, dead model upstreams.
#
#   ./preflight.sh               # full check + fix + eval pre-run
#   ./preflight.sh --skip-evals  # skip the eval pre-run step
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AMD="$(cd "$SCRIPT_DIR/../agent-mesh-deployment" && pwd)"
SAM_URL="https://sam.solace.lab"

# ---- demo-specific configuration ----------------------------------
REQUIRED_AGENTS=("Orchestrator" "Acme CRM Query Expert" \
  "Acme OMS Query Expert" "Acme PDM Query Expert" \
  "Acme SCM Query Expert" "Production Confirmation Clerk" \
  "Quality Incident Reporter" "Supply Chain Watcher")
FORBIDDEN_AGENT="Shop Floor Analyst"
REQUIRED_CONNECTORS=("Acme CRM DB" "Acme OMS DB" "Acme PDM DB" \
  "Acme SCM DB" "mfg-telemetry" "mfg-consumption")
REQUIRED_WORKFLOWS=("quality-incident-report" "supply-replenishment")
REQUIRED_ENTRYPOINT="plant-events"
MY_MONGO="mfg-plant-mongo"; OTHER_MONGO="retail-pos-mongo"
MONGO_DB="mfg_plant"
EVAL_EXPERIMENTS=("mfg-ops-quality" "mfg-ops-model-benchmark")
DASHBOARD_CM="dashboard-sam-mfg-ops"
DASHBOARD_FILE="$SCRIPT_DIR/observability/dashboard-sam-mfg-ops.yaml"

mongo_counts_ok() {
  docker exec "$MY_MONGO" mongosh -u sam_ro -p sam_ro \
    --authenticationDatabase "$MONGO_DB" "$MONGO_DB" --quiet --eval '
    const t=db.station_telemetry.countDocuments({});
    const c=db.material_consumption.countDocuments({});
    if (t>=900 && c>=250) print("OK "+t+"/"+c); else print("BAD "+t+"/"+c);' \
    2>/dev/null | grep -q '^OK'
}

sql_spot_ok() {
  local eco hold hd22
  eco=$(docker exec postgres psql -U postgres -d mfg_pdm -tAc \
    "SELECT status FROM mfg_eco_distribution WHERE eco_id='ECO-2025-118' AND plant_id='PLANT_GRZ';" 2>/dev/null)
  hold=$(docker exec postgres psql -U postgres -d mfg_oms -tAc \
    "SELECT count(*) FROM mfg_production_orders WHERE prod_order_id='PRD-118-4718' AND status='QUALITY_HOLD';" 2>/dev/null)
  hd22=$(docker exec postgres psql -U postgres -d mfg_scm -tAc \
    "SELECT on_hand_qty FROM mfg_inventory WHERE plant_id='PLANT_HAM' AND material_id='MAT_CLT_HD22';" 2>/dev/null)
  [ "$eco" = "PENDING" ] && [ "$hold" = "1" ] && [ "$hd22" = "1850" ]
}

# ---- generic engine -----------------------------------------------
SKIP_EVALS=0
case "${1:-}" in
  --skip-evals) SKIP_EVALS=1 ;;
  -h|--help) grep '^#   \./' "$0" | sed 's/^#   //'; exit 0 ;;
  "") ;;
  *) echo "Unknown argument: $1" >&2; exit 1 ;;
esac

PASS=0; FIXED=0; FAILED=0
ok()   { echo "   [OK]    $1"; PASS=$((PASS+1)); }
fixd() { echo "   [FIXED] $1"; FIXED=$((FIXED+1)); }
bad()  { echo "   [FAIL]  $1"; FAILED=$((FAILED+1)); }

# shellcheck source=../agent-mesh-deployment/scripts/lib/common.sh
. "$AMD/scripts/lib/common.sh"
load_env "$AMD"
resolve_sam_cli >/dev/null 2>&1 || resolve_sam_cli

api() {  # api METHOD PATH -> body on stdout, code in API_CODE
  local method="$1" path="$2"
  API_CODE=$(curl -sk -m 20 -X "$method" "$SAM_URL$path" \
    -H "Authorization: Bearer $SAM_AUTH_TOKEN" \
    -o /tmp/preflight-body.json -w "%{http_code}")
  cat /tmp/preflight-body.json 2>/dev/null || true
}
names_of() { python3 -c "
import json,sys
try:
    for x in json.load(sys.stdin).get('data',[]): print(x.get('name',''))
except Exception: pass"; }
id_of() { python3 -c "
import json,sys
try:
    for x in json.load(sys.stdin).get('data',[]):
        if x.get('name')=='$1': print(x['id'])
except Exception: pass"; }

echo "== 1/8 Platform login + API"
(cd "$SCRIPT_DIR/eval" && "$SAM_CLI" config plan >/dev/null 2>&1)  # token refresh
sam_auth_token >/dev/null 2>&1
api GET /api/v1/platform/agents >/dev/null
if [ "${API_CODE:-}" = "200" ]; then
  ok "platform API reachable, token fresh"
else
  bad "platform API HTTP ${API_CODE:-?} -- manual fix: sam auth login solace-lab --url $SAM_URL"
  echo ""; echo "ABORT: everything else needs the API."; exit 1
fi

echo "== 2/8 Cluster health"
BADPODS=$(kubectl get pods -A --no-headers 2>/dev/null \
  | awk '$4!="Running" && $4!="Completed" && $4!="Succeeded" {print $1"/"$2" "$4}')
if [ -z "$BADPODS" ]; then
  ok "all pods Running/Completed"
else
  echo "$BADPODS" | sed 's/^/          /'
  bad "unhealthy pods (no auto-fix -- see memory: clock wedge / stale IP runbooks)"
fi

echo "== 3/8 Model upstreams (1-token probes)"
if "$AMD/scripts/models/apply-models.sh" --probe-only >/tmp/preflight-models.log 2>&1; then
  ok "all model upstreams answered"
else
  tail -5 /tmp/preflight-models.log | sed 's/^/          /'
  bad "model probe failed (no auto-fix -- external gateway; retry or demo without that alias)"
fi

echo "== 4/8 Platform resources (roster, connectors, workflows, entrypoint)"
missing=""
AG=$(api GET /api/v1/platform/agents | names_of)
CO=$(api GET /api/v1/platform/connectors | names_of)
WF=$(api GET /api/v1/platform/workflows | names_of)
GW=$(api GET /api/v1/platform/gateways | names_of)
for a in "${REQUIRED_AGENTS[@]}";     do grep -qxF "$a" <<<"$AG" || missing+="agent:$a "; done
for c in "${REQUIRED_CONNECTORS[@]}"; do grep -qxF "$c" <<<"$CO" || missing+="connector:$c "; done
for w in "${REQUIRED_WORKFLOWS[@]}";  do grep -qxF "$w" <<<"$WF" || missing+="workflow:$w "; done
grep -qxF "$REQUIRED_ENTRYPOINT" <<<"$GW" || missing+="entrypoint:$REQUIRED_ENTRYPOINT "
if [ -n "$missing" ]; then
  echo "          missing: $missing"
  echo "          fix: running ./install.sh (idempotent) ..."
  (cd "$SCRIPT_DIR" && ./install.sh >/tmp/preflight-install.log 2>&1)
  AG=$(api GET /api/v1/platform/agents | names_of)
  CO=$(api GET /api/v1/platform/connectors | names_of)
  WF=$(api GET /api/v1/platform/workflows | names_of)
  GW=$(api GET /api/v1/platform/gateways | names_of)
  missing=""
  for a in "${REQUIRED_AGENTS[@]}";     do grep -qxF "$a" <<<"$AG" || missing+="agent:$a "; done
  for c in "${REQUIRED_CONNECTORS[@]}"; do grep -qxF "$c" <<<"$CO" || missing+="connector:$c "; done
  for w in "${REQUIRED_WORKFLOWS[@]}";  do grep -qxF "$w" <<<"$WF" || missing+="workflow:$w "; done
  grep -qxF "$REQUIRED_ENTRYPOINT" <<<"$GW" || missing+="entrypoint:$REQUIRED_ENTRYPOINT "
  if [ -z "$missing" ]; then fixd "platform resources (via install.sh; log: /tmp/preflight-install.log)"
  else bad "still missing after install.sh: $missing"; fi
else
  ok "all required resources present"
fi
FID=$(api GET /api/v1/platform/agents | id_of "$FORBIDDEN_AGENT")
if [ -n "$FID" ]; then
  api DELETE "/api/v1/platform/agents/$FID" >/dev/null
  [ "$API_CODE" = "204" ] && fixd "'$FORBIDDEN_AGENT' removed (live Builder beat)" \
    || bad "'$FORBIDDEN_AGENT' delete returned HTTP $API_CODE"
else
  ok "'$FORBIDDEN_AGENT' absent (live Builder beat is free)"
fi

echo "== 5/8 Postgres storyline data"
"$SCRIPT_DIR/postgres/seed.sh" >/tmp/preflight-seed.log 2>&1
if sql_spot_ok; then ok "seeded + spot-checks (ECO PENDING, QUALITY_HOLD, HD-22 1850)"
else bad "spot-checks failed after seed (see /tmp/preflight-seed.log)"; fi

echo "== 6/8 MongoDB plant store"
if [ "$(docker inspect -f '{{.State.Running}}' "$OTHER_MONGO" 2>/dev/null)" = "true" ]; then
  docker stop "$OTHER_MONGO" >/dev/null && fixd "$OTHER_MONGO stopped (port 27017 rule)"
fi
docker compose -f "$SCRIPT_DIR/mongodb/docker-compose.yaml" up -d >/dev/null 2>&1
sleep 3
if mongo_counts_ok; then
  ok "$MY_MONGO up, doc counts good"
else
  echo "          fix: recreating $MY_MONGO with fresh seed ..."
  docker compose -f "$SCRIPT_DIR/mongodb/docker-compose.yaml" down -v >/dev/null 2>&1
  docker compose -f "$SCRIPT_DIR/mongodb/docker-compose.yaml" up -d >/dev/null 2>&1
  for _ in $(seq 1 12); do sleep 5; mongo_counts_ok && break; done
  if mongo_counts_ok; then fixd "$MY_MONGO reseeded"
  else bad "$MY_MONGO counts still wrong after reseed"; fi
fi

echo "== 7/8 Broker WebSocket (cockpit path)"
ws_ok() {  # pipefail-safe: curl exits 28 after the upgrade stream
  curl -si -m 5 -H "Connection: Upgrade" -H "Upgrade: websocket" \
    -H "Sec-WebSocket-Version: 13" \
    -H "Sec-WebSocket-Key: cHJlZmxpZ2h0Y2hlY2sxMg==" \
    http://localhost:8008/ >/tmp/preflight-ws.txt 2>/dev/null || true
  head -1 /tmp/preflight-ws.txt 2>/dev/null | grep -q "101"
}
if ws_ok; then
  ok "ws://localhost:8008 answers 101 (cockpit LED will be green)"
else
  if docker inspect solace-1 >/dev/null 2>&1; then
    echo "          fix: starting broker containers ..."
    docker start solace-1 solace-2 >/dev/null 2>&1
    for _ in $(seq 1 18); do sleep 5; ws_ok && break; done
    if ws_ok; then fixd "brokers started, WS up"
    else bad "WS still down -- run: cd event-mesh-deployment && ./start.sh"; fi
  else
    bad "no broker containers -- run: cd event-mesh-deployment && ./start.sh"
  fi
fi

echo "== 8/8 Dashboard + eval pre-runs"
if kubectl get cm -n sam-solace-lab "$DASHBOARD_CM" >/dev/null 2>&1; then
  ok "Grafana dashboard ConfigMap present"
else
  kubectl apply -f "$DASHBOARD_FILE" >/dev/null 2>&1 \
    && fixd "dashboard ConfigMap applied" || bad "dashboard apply failed"
fi
if [ "$SKIP_EVALS" -eq 1 ]; then
  echo "   [SKIP]  eval pre-runs (--skip-evals)"
else
  for exp in "${EVAL_EXPERIMENTS[@]}"; do
    EID=$(api GET /api/v1/platform/evaluations/experiments | id_of "$exp")
    if [ -z "$EID" ]; then bad "experiment '$exp' not on platform"; continue; fi
    if api GET "/api/v1/platform/evaluations/experiments/$EID/runs" \
        | grep -q '"completed"'; then
      ok "experiment '$exp' has a completed run"
    else
      echo "          fix: running '$exp' (this is the ~15-min part) ..."
      if "$SAM_CLI" eval run "$exp" --url "$SAM_URL" 2>&1 | tail -3 | sed 's/^/          /' \
         && api GET "/api/v1/platform/evaluations/experiments/$EID/runs" | grep -q '"completed"'; then
        fixd "experiment '$exp' pre-run completed"
      else
        bad "experiment '$exp' run did not complete"
      fi
    fi
  done
fi

echo ""
echo "== Manual reminders (not automatable)"
echo "   - Windows: A sam_admin (Agent Management), B power_user"
echo "     (Activities), C cockpit/index.html (LED green), D Grafana."
echo "   - Links: ./demo-links.sh"
echo "   - Rehearsed break-glass buttons? RESET the cockpit after."
echo "   - Never open the Builder's Test tab on stage."
echo ""
echo "== Result: $PASS ok, $FIXED fixed, $FAILED failed"
if [ "$FAILED" -eq 0 ]; then
  echo "READY -- the demo environment is validated."
  exit 0
else
  echo "NOT READY -- resolve the [FAIL] items above."
  exit 1
fi
