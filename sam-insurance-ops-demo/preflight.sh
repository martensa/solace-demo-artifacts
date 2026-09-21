#!/bin/bash
set -uo pipefail

# =============================================================
# preflight.sh -- automated pre-flight checklist (talk-track.md
# Appendix A) with AUTO-FIX. Run ~15 minutes before going live;
# after a clean run the environment is validated and demo-ready.
#
# PROFILE-AWARE: the installed profile is detected from the
# entrypoints on the platform (claims-triage => triage,
# claims-events => extended; neither => FAIL with the install
# hint). Shared checks (login, cluster, models, data stores,
# broker WebSocket) run for both; each profile adds its own.
#
# Every check that fails triggers its fix and re-checks:
#   platform resources missing   -> ./install.sh [--extended]
#   entrypoint not deployed      -> entrypointDeployments deploy (triage)
#   external agent not ready     -> kubectl apply external-agent/ (triage)
#   Storm Intake Analyst present -> deleted (extended, live Builder beat)
#   postgres data                -> postgres/seed.sh + spot-check
#   wrong/empty mongo            -> compose down -v && up (reseed)
#   other demos' mongo running   -> stopped (port 27017 rule)
#   qdrant empty / MCP down      -> compose up --build + reseed
#   broker WS down               -> docker start solace-1/2, retry
#   dashboard ConfigMap missing  -> kubectl apply
#   datasource CM / grant missing-> grant-grafana-platform-db.sh (triage)
#   evals without completed runs -> sam eval run (the 15-min part)
# WARN only: no Tempo traces in the last 24 h (triage).
# Triage ends with a DRY FIRE (tools/fire-claim.js) that must
# print a decision -- it warms the agents; the cockpit stays
# untouched.
# Not auto-fixable (reported with instructions): sam login
# (browser flow), unhealthy cluster pods, dead model upstreams,
# a liaison whose DEPLOYED allow list does not name the external
# analyst, an undiscovered external agent, a failed dry fire.
#
#   ./preflight.sh               # full check + fix + eval pre-run
#   ./preflight.sh --skip-evals  # skip the eval pre-run step
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AMD="$(cd "$SCRIPT_DIR/../agent-mesh-deployment" && pwd)"
SAM_URL="https://sam.solace.lab"

# ---- shared configuration -----------------------------------------
MY_MONGO="acme-claims-mongo"
OTHER_MONGOS=("retail-pos-mongo" "mfg-plant-mongo")
MONGO_DB="acme_claims"
MONGO_COMPOSE="$SCRIPT_DIR/mongodb/docker-compose.yaml"
QDRANT_COMPOSE="$SCRIPT_DIR/qdrant/docker-compose.yaml"
QDRANT_COLLECTION_URL="http://localhost:6333/collections/acme_knowledge"
MCP_HEALTH_URL="http://localhost:8765/health"
SAM_NS="sam-solace-lab"
MON_NS="monitoring"
PG_POD="agent-mesh-postgresql-0"
PLATFORM_DB="sam-solace-lab_platform"
# ---- triage profile -------------------------------------------------
EXT_NS="sam-solace-lab-agents"
EXT_DEPLOY="sam-claims-intake-agent"
EXT_CARD="ClaimsIntakeAnalyst"
LIAISON_AGENT="Claims Intake Liaison"
DATASOURCE_CM="grafana-datasource-sam-platform-config"
DATASOURCE_FILE="$AMD/manifests/observability/$DATASOURCE_CM.yaml"
GRANT_SCRIPT="$AMD/scripts/observability/grant-grafana-platform-db.sh"
FIRE_JS="$SCRIPT_DIR/tools/fire-claim.js"
FIRE_CLAIM="CLM-0913-00002"
FIRE_WAIT=90

mongo_counts_ok() {
  docker exec "$MY_MONGO" mongosh -u sam_ro -p sam_ro \
    --authenticationDatabase "$MONGO_DB" "$MONGO_DB" --quiet --eval '
    const f=db.fnol_intake.countDocuments({});
    const w=db.weather_cells.countDocuments({});
    const s=db.scanner_results.countDocuments({});
    // The external analyst reads ONE thing: the claim_intake_facts
    // view from 02-anchors.js. A store without it answers every
    // claim with "intake unavailable".
    const v=db.getCollectionInfos({name:"claim_intake_facts"}).length;
    if (f>=10400 && w==3 && s>=1000 && v==1) print("OK "+f+"/"+w+"/"+s+"/v"+v);
    else print("BAD "+f+"/"+w+"/"+s+"/v"+v);' \
    2>/dev/null | grep -q '^OK'
}

sql_spot_ok() {
  # The demo's "now" is Mon 2026-07-20 10:00 (fixed in the data),
  # so the > 4 h stalled cohort is measured against that instant.
  local cohort braendle dellendoc nogarage payitems
  cohort=$(docker exec postgres psql -U postgres -d acme_insurance -tAc \
    "SELECT count(*) FROM ins_claims WHERE status='AWAITING_WORKSHOP_SLOT' AND assigned_partner_id='P-BRAENDLE' AND status_since < TIMESTAMP '2026-07-20 10:00:00' - INTERVAL '4 hours';" 2>/dev/null)
  braendle=$(docker exec postgres psql -U postgres -d acme_insurance -tAc \
    "SELECT count(*) FROM ins_claims WHERE status='AWAITING_WORKSHOP_SLOT' AND assigned_partner_id='P-BRAENDLE';" 2>/dev/null)
  dellendoc=$(docker exec postgres psql -U postgres -d acme_insurance -tAc \
    "SELECT contract_status FROM ins_repair_partners WHERE partner_id='P-DELLENDOC';" 2>/dev/null)
  nogarage=$(docker exec postgres psql -U postgres -d acme_insurance -tAc \
    "SELECT count(*) FROM ins_policies WHERE district='LUDWIGSBURG' AND product LIKE 'MOTOR%' AND garage_parking=false;" 2>/dev/null)
  payitems=$(docker exec postgres psql -U postgres -d acme_insurance -tAc \
    "SELECT count(*) FROM ins_payment_items WHERE payment_run_id='PR-2026-30';" 2>/dev/null)
  [ "$cohort" = "412" ] && [ "$braendle" = "640" ] \
    && [ "$dellendoc" = "INACTIVE" ] && [ "$nogarage" = "8900" ] \
    && [ "$payitems" = "3900" ]
}

qdrant_points_ok() {  # acme_knowledge collection present with >= 40 points
  local n
  n=$(curl -s -m 5 "$QDRANT_COLLECTION_URL" 2>/dev/null | python3 -c "
import json,sys
try: print(json.load(sys.stdin)['result']['points_count'])
except Exception: print(0)" 2>/dev/null)
  [ "${n:-0}" -ge 40 ] 2>/dev/null
}

mcp_health_ok() {
  [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' "$MCP_HEALTH_URL" \
    2>/dev/null)" = "200" ]
}

ext_ready() {  # external agent deployment has a ready replica
  local n
  n=$(kubectl get deploy -n "$EXT_NS" "$EXT_DEPLOY" \
    -o jsonpath='{.status.readyReplicas}' 2>/dev/null)
  [ "${n:-0}" -ge 1 ] 2>/dev/null
}

card_present() {  # the external agent's card is in the mesh
  # /api/v1/agentCards answers {data:[...]} today; a bare list is
  # tolerated as well. External v1-SDK agents publish their
  # agent_name as the card name (verified: WebResearchAgent).
  api GET /api/v1/agentCards | python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception: sys.exit(1)
cards=d if isinstance(d,list) else (d.get('data') or d.get('agentCards') or [])
sys.exit(0 if any(isinstance(c,dict) and c.get('name')==sys.argv[1]
                  for c in cards) else 1)" "$EXT_CARD"
}

liaison_allowlist() {  # "<source>|<comma-joined allowList>" of the liaison
  # Peer delegation exists ONLY where an agent config carries
  # interAgentCommunication.allowList (the built-in Orchestrator has
  # it set to ["*"]); the liaison's one-name list is the declared way
  # out of the platform. Read from the DEPLOYED snapshot
  # (agent.deployed), not the draft record: an edited but not
  # redeployed agent still runs the old config. Source is
  # 'undeployed'/'absent'/'unreadable' when there is none.
  api GET /api/v1/platform/agents | python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception: print('unreadable|'); sys.exit(0)
for a in d.get('data',[]):
    if a.get('name')==sys.argv[1]:
        dep=a.get('deployed')
        src='deployed' if isinstance(dep,dict) else 'undeployed'
        cfg=(dep if isinstance(dep,dict) else a).get('additionalConfigurations') or {}
        peers=(cfg.get('interAgentCommunication') or {}).get('allowList') or []
        print(src+'|'+','.join(str(p) for p in peers)); sys.exit(0)
print('absent|')" "$LIAISON_AGENT"
}

grant_ok() {  # grafana_ro may SELECT eval_runs in the platform DB
  # $POSTGRES_PASSWORD expands INSIDE the pod (single quotes on purpose).
  # shellcheck disable=SC2016
  kubectl exec -n "$SAM_NS" "$PG_POD" -- bash -c \
    'PGPASSWORD=$POSTGRES_PASSWORD psql -U postgres -d '"$PLATFORM_DB"' -tAc "SELECT has_table_privilege('"'"'grafana_ro'"'"','"'"'eval_runs'"'"','"'"'SELECT'"'"')"' \
    2>/dev/null | grep -qx t
}

tempo_trace_count() {  # traces in the last 24 h ("0" on any error)
  local now
  now=$(date +%s)
  kubectl get --raw "/api/v1/namespaces/$MON_NS/services/tempo:3200/proxy/api/search?limit=1&start=$((now-86400))&end=$now" \
    2>/dev/null | python3 -c "
import json,sys
try: print(len(json.load(sys.stdin).get('traces') or []))
except Exception: print(0)" 2>/dev/null
}

# ---- generic engine -----------------------------------------------
SKIP_EVALS=0
case "${1:-}" in
  --skip-evals) SKIP_EVALS=1 ;;
  -h|--help) grep '^#   \./' "$0" | sed 's/^#   //'; exit 0 ;;
  "") ;;
  *) echo "Unknown argument: $1" >&2; exit 1 ;;
esac

PASS=0; FIXED=0; WARNED=0; FAILED=0; STEP=0; TOTAL=0
ok()   { echo "   [OK]    $1"; PASS=$((PASS+1)); }
fixd() { echo "   [FIXED] $1"; FIXED=$((FIXED+1)); }
warn() { echo "   [WARN]  $1"; WARNED=$((WARNED+1)); }
bad()  { echo "   [FAIL]  $1"; FAILED=$((FAILED+1)); }
step() { STEP=$((STEP+1)); echo "== $STEP/$TOTAL $1"; }

# shellcheck source=../agent-mesh-deployment/scripts/lib/common.sh
. "$AMD/scripts/lib/common.sh"
load_env "$AMD"
resolve_sam_cli >/dev/null 2>&1 || resolve_sam_cli

api() {  # api METHOD PATH -> body on stdout, code in API_CODE
  local method="$1" path="$2"
  # 2.348.22 pages every list endpoint (default 20 per page, newest
  # first): read the maximum page of 100 (the demos stay far below).
  [ "$method" = GET ] && case "$path" in *\?*) ;; *) path="$path?pageSize=100" ;; esac
  API_CODE=$(curl -sk -m 20 -X "$method" "$SAM_URL$path" \
    -H "Authorization: Bearer $SAM_AUTH_TOKEN" \
    -o /tmp/preflight-body.json -w "%{http_code}")
  cat /tmp/preflight-body.json 2>/dev/null || true
}
api_json() {  # api_json METHOD PATH JSON -> body on stdout, code in API_CODE
  local method="$1" path="$2" body="$3"
  API_CODE=$(curl -sk -m 20 -X "$method" "$SAM_URL$path" \
    -H "Authorization: Bearer $SAM_AUTH_TOKEN" \
    -H "Content-Type: application/json" -d "$body" \
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
field_of() {  # field_of NAME FIELD -> the field of the named list item
  # A status field may be a plain string (2.225.14) or an object
  # {"status": "running"} (runtimeStatus since 2.348.22) -- print the
  # status string in both cases.
  python3 -c "
import json,sys
try:
    for x in json.load(sys.stdin).get('data',[]):
        if x.get('name')==sys.argv[1]:
            v=x.get(sys.argv[2],'')
            print(v.get('status','') if isinstance(v,dict) else (v or ''))
except Exception: pass" "$1" "$2"; }

# ---- profile detection (before the first numbered step: the step
#      count depends on it) -----------------------------------------
(cd "$SCRIPT_DIR/eval" && "$SAM_CLI" config plan >/dev/null 2>&1)  # token refresh
sam_auth_token >/dev/null 2>&1
# Without a login cache sam_auth_token leaves SAM_AUTH_TOKEN unset and
# `set -u` would kill the run with a bare shell error. An empty token
# is the better failure: the api call below answers 401 and step 1
# reports it with the login hint (the documented manual fix).
SAM_AUTH_TOKEN="${SAM_AUTH_TOKEN:-}"
api GET /api/v1/platform/agents >/dev/null
API_OK="${API_CODE:-}"
PROFILE=""
if [ "$API_OK" = "200" ]; then
  GW=$(api GET /api/v1/platform/entrypoints | names_of)
  if grep -qxF claims-triage <<<"$GW"; then PROFILE=triage
  elif grep -qxF claims-events <<<"$GW"; then PROFILE=extended
  fi
fi
if [ "$PROFILE" = "triage" ]; then
  TOTAL=13
  # PLATFORM agents only -- the four the workflow's nodes bind to.
  # The intake node runs on the Claims Intake Liaison, whose single
  # declared peer is the EXTERNAL Claims Intake Analyst: that one is
  # not a platform record and is checked separately below (the
  # liaison's allow list, the deployment, the agent card).
  REQUIRED_AGENTS=("Acme Insurance Query Expert" \
    "Acme Claims Knowledge Expert" "Claims Intake Liaison" \
    "Claims Triage Decision")
  REQUIRED_CONNECTORS=("Acme Insurance DB" "Acme Claims Knowledge")
  REQUIRED_WORKFLOWS=("claim-triage")
  REQUIRED_ENTRYPOINT="claims-triage"
  EVAL_EXPERIMENTS=("ins-ops-quality" "ins-ops-model-benchmark" \
    "ins-claims-rules" "ins-guardrails" "ins-triage-decision")
  DASHBOARD_CMS=("dashboard-sam-claims-governance" "dashboard-sam-insurance-ops")
  INSTALL_ARGS=""
else
  TOTAL=9
  REQUIRED_AGENTS=("Orchestrator" "Acme Insurance Query Expert" \
    "Acme Claims Knowledge Expert" "Fast Lane Clerk" \
    "Claims Incident Reporter" "Storm Readiness Planner" \
    "Fraud Case Reporter")
  FORBIDDEN_AGENT="Storm Intake Analyst"
  REQUIRED_CONNECTORS=("Acme Insurance DB" "Acme Claims Knowledge" \
    "fnol-intake" "weather-cells" "scanner-results")
  REQUIRED_WORKFLOWS=("stalled-cohort-report" "storm-readiness" \
    "cross-channel-fraud-report")
  REQUIRED_ENTRYPOINT="claims-events"
  EVAL_EXPERIMENTS=("ins-ops-quality" "ins-ops-model-benchmark")
  DASHBOARD_CMS=("dashboard-sam-insurance-ops")
  INSTALL_ARGS="--extended"
fi

step "Platform login + API + profile"
if [ "$API_OK" = "200" ]; then
  ok "platform API reachable, token fresh"
else
  bad "platform API HTTP ${API_OK:-?} -- manual fix: sam auth login solace-lab --url $SAM_URL"
  echo ""; echo "ABORT: everything else needs the API."; exit 1
fi
if [ -n "$PROFILE" ]; then
  ok "profile: $PROFILE (entrypoint '$REQUIRED_ENTRYPOINT' on the platform)"
else
  bad "no demo entrypoint on the platform (neither claims-triage nor claims-events) -- install first: ./install.sh (triage) or ./install.sh --extended"
  echo ""; echo "ABORT: the profile decides which checks apply."; exit 1
fi

step "Cluster health"
BADPODS=$(kubectl get pods -A --no-headers 2>/dev/null \
  | awk '$4!="Running" && $4!="Completed" && $4!="Succeeded" {print $1"/"$2" "$4}')
if [ -z "$BADPODS" ]; then
  ok "all pods Running/Completed"
else
  echo "$BADPODS" | sed 's/^/          /'
  bad "unhealthy pods (no auto-fix -- see memory: clock wedge / stale IP runbooks)"
fi

step "Model upstreams (1-token probes)"
if "$AMD/scripts/models/apply-models.sh" --probe-only >/tmp/preflight-models.log 2>&1; then
  ok "all model upstreams answered"
else
  tail -5 /tmp/preflight-models.log | sed 's/^/          /'
  bad "model probe failed (no auto-fix -- external gateway; retry or demo without that alias)"
fi

step "Platform resources (roster, connectors incl. MCP, workflows, entrypoint)"
collect_missing() {  # -> sets MISSING from the live platform
  local AG CO WF GW a c w
  MISSING=""
  AG=$(api GET /api/v1/platform/agents | names_of)
  CO=$(api GET /api/v1/platform/connectors | names_of)
  WF=$(api GET /api/v1/platform/workflows | names_of)
  GW=$(api GET /api/v1/platform/entrypoints | names_of)
  for a in "${REQUIRED_AGENTS[@]}";     do grep -qxF "$a" <<<"$AG" || MISSING+="agent:$a "; done
  for c in "${REQUIRED_CONNECTORS[@]}"; do grep -qxF "$c" <<<"$CO" || MISSING+="connector:$c "; done
  for w in "${REQUIRED_WORKFLOWS[@]}";  do grep -qxF "$w" <<<"$WF" || MISSING+="workflow:$w "; done
  grep -qxF "$REQUIRED_ENTRYPOINT" <<<"$GW" || MISSING+="entrypoint:$REQUIRED_ENTRYPOINT "
}
collect_missing
if [ -n "$MISSING" ]; then
  echo "          missing: $MISSING"
  echo "          fix: running ./install.sh $INSTALL_ARGS (idempotent) ..."
  # shellcheck disable=SC2086
  (cd "$SCRIPT_DIR" && ./install.sh $INSTALL_ARGS >/tmp/preflight-install.log 2>&1)
  collect_missing
  if [ -z "$MISSING" ]; then fixd "platform resources (via install.sh; log: /tmp/preflight-install.log)"
  else bad "still missing after install.sh: $MISSING"; fi
else
  ok "all required resources present"
fi
if [ "$PROFILE" = "triage" ]; then
  # Deployment state matters here: an undeployed workflow never
  # answers and an undeployed entrypoint has no broker receiver.
  WF_DEP=$(api GET /api/v1/platform/workflows | field_of claim-triage deploymentStatus)
  WF_RUN=$(api GET /api/v1/platform/workflows | field_of claim-triage runtimeStatus)
  if [ "$WF_DEP" = "deployed" ] && [ "$WF_RUN" = "running" ]; then
    ok "workflow claim-triage deployed + running"
  elif [ "$WF_DEP" = "deployed" ]; then
    warn "workflow claim-triage deployed but runtimeStatus='$WF_RUN' (awe restart pending? check Workflows page)"
  else
    bad "workflow claim-triage deploymentStatus='$WF_DEP' -- fix: bump appConfig.version in triage/workflows/claim-triage.yaml, then ./install.sh (re-renders the entrypoint)"
  fi
  EP_DEP=$(api GET /api/v1/platform/entrypoints | field_of claims-triage deploymentStatus)
  if [ "$EP_DEP" = "deployed" ]; then
    ok "entrypoint claims-triage deployed"
  else
    EPID=$(api GET /api/v1/platform/entrypoints | id_of claims-triage)
    echo "          fix: deploying entrypoint claims-triage ($EPID, status '$EP_DEP') ..."
    api_json POST /api/v1/platform/entrypointDeployments \
      "{\"gatewayId\":\"$EPID\",\"action\":\"deploy\"}" >/dev/null
    for _ in $(seq 1 8); do
      sleep 5
      EP_DEP=$(api GET /api/v1/platform/entrypoints | field_of claims-triage deploymentStatus)
      [ "$EP_DEP" = "deployed" ] && break
    done
    if [ "$EP_DEP" = "deployed" ]; then fixd "entrypoint claims-triage deployed (receivers follow within about a second)"
    else bad "entrypoint claims-triage still '$EP_DEP' (deploy POST -> HTTP $API_CODE)"; fi
  fi
else
  FID=$(api GET /api/v1/platform/agents | id_of "$FORBIDDEN_AGENT")
  if [ -n "$FID" ]; then
    api DELETE "/api/v1/platform/agents/$FID" >/dev/null
    [ "$API_CODE" = "204" ] && fixd "'$FORBIDDEN_AGENT' removed (live Builder beat)" \
      || bad "'$FORBIDDEN_AGENT' delete returned HTTP $API_CODE"
  else
    ok "'$FORBIDDEN_AGENT' absent (live Builder beat is free)"
  fi
fi

if [ "$PROFILE" = "triage" ]; then
step "Intake hop: liaison allow list + external agent (ns $EXT_NS)"
# The platform half of the hop first. Without
# interAgentCommunication.allowList naming $EXT_CARD the liaison has
# no peer tool at all: every claim still produces a decision and
# every decision reads "intake unavailable" -- the one failure that
# looks like a working demo. Read-only on purpose; re-applying an
# agent config is not something to do 15 minutes before going live.
AL_RAW=$(liaison_allowlist)
AL_SRC="${AL_RAW%%|*}"
AL_LIST="${AL_RAW#*|}"
if [ "$AL_SRC" != "deployed" ]; then
  bad "no deployed config for '$LIAISON_AGENT' ($AL_SRC) -- fix: ./install.sh, then check the agent in Agent Management (an undeployed liaison never answers the intake node)"
elif [[ ",$AL_LIST," == *",$EXT_CARD,"* ]]; then
  ok "'$LIAISON_AGENT' may call $EXT_CARD (deployed allowList: $AL_LIST)"
else
  bad "deployed allowList of '$LIAISON_AGENT' is '${AL_LIST:-<empty>}' and does not name $EXT_CARD -- the agent gets no peer tool and every claim answers 'intake unavailable'. Fix: restore additionalConfigurations.interAgentCommunication.allowList in triage/agents/Claims Intake Liaison.yaml, re-apply with ./install.sh, then redeploy the agent"
fi
if ext_ready; then
  ok "deployment $EXT_DEPLOY ready (pod Running)"
else
  echo "          fix: kubectl apply -f external-agent/ + rollout wait (120 s) ..."
  kubectl apply -f "$SCRIPT_DIR/external-agent/" >/tmp/preflight-ext.log 2>&1
  kubectl rollout status "deployment/$EXT_DEPLOY" -n "$EXT_NS" --timeout=120s \
    >>/tmp/preflight-ext.log 2>&1
  if ext_ready; then fixd "$EXT_DEPLOY applied and ready"
  else bad "$EXT_DEPLOY not ready -- kubectl -n $EXT_NS describe deploy/$EXT_DEPLOY; logs deploy/$EXT_DEPLOY"; fi
fi
if card_present; then
  ok "card '$EXT_CARD' discovered (GET /api/v1/agentCards)"
else
  echo "          waiting up to 60 s for the card (published every 10 s) ..."
  T0=$(date +%s); FOUND=0
  for _ in $(seq 1 12); do
    sleep 5
    if card_present; then FOUND=1; break; fi
  done
  if [ "$FOUND" -eq 1 ]; then fixd "card '$EXT_CARD' discovered after $(( $(date +%s) - T0 )) s"
  else bad "card '$EXT_CARD' not in the mesh -- kubectl -n $EXT_NS logs deploy/$EXT_DEPLOY (broker creds from sam-shared-secret? 'MongoDB Agent initialization completed successfully'?)"; fi
fi
fi

step "Postgres storyline data"
"$SCRIPT_DIR/postgres/seed.sh" >/tmp/preflight-seed.log 2>&1
if sql_spot_ok; then ok "seeded + spot-checks (412 cohort > 4 h, 640 at P-BRAENDLE, P-DELLENDOC INACTIVE, 8,900 no-garage LB, 3,900 payment items)"
else bad "spot-checks failed after seed (see /tmp/preflight-seed.log)"; fi

step "MongoDB claims store"
for other in "${OTHER_MONGOS[@]}"; do
  if [ "$(docker inspect -f '{{.State.Running}}' "$other" 2>/dev/null)" = "true" ]; then
    docker stop "$other" >/dev/null && fixd "$other stopped (port 27017 rule)"
  fi
done
docker compose -f "$MONGO_COMPOSE" up -d >/dev/null 2>&1
# A cold mongod does not accept authenticated queries for several
# seconds after `up -d`. Give it ~30 s before concluding the store is
# wrong: the fix path below DESTROYS the volume and reseeds, which is
# slow and pointless when the store was only still starting.
for _ in $(seq 1 10); do mongo_counts_ok && break; sleep 3; done
if mongo_counts_ok; then
  ok "$MY_MONGO up, doc counts good (fnol_intake >= 10,400, weather_cells 3, scanner_results >= 1,000, claim_intake_facts view present)"
else
  echo "          fix: recreating $MY_MONGO with fresh seed ..."
  docker compose -f "$MONGO_COMPOSE" down -v >/dev/null 2>&1
  docker compose -f "$MONGO_COMPOSE" up -d >/dev/null 2>&1
  # First init runs both seed scripts (10,400+ documents, the view).
  for _ in $(seq 1 36); do sleep 5; mongo_counts_ok && break; done
  if mongo_counts_ok; then fixd "$MY_MONGO reseeded"
  else bad "$MY_MONGO counts still wrong after reseed"; fi
fi

step "Qdrant knowledge base + MCP server"
if qdrant_points_ok && mcp_health_ok; then
  ok "acme_knowledge >= 40 points (REST 6333), MCP /health 200 (8765)"
else
  echo "          fix: compose up --build + re-running the corpus seed"
  echo "          (first run downloads the embedding model; up to 6 min) ..."
  docker compose -f "$QDRANT_COMPOSE" up -d --build >/tmp/preflight-qdrant.log 2>&1
  # Qdrant REST must answer before the one-shot seed can write.
  for _ in $(seq 1 24); do
    curl -s -m 3 -o /dev/null http://localhost:6333/collections 2>/dev/null && break
    sleep 5
  done
  # `compose run` is not an option here: the seed service carries a
  # fixed container_name, so a one-off run collides with the exited
  # container of the install. Recreating the service re-runs the
  # one-shot seed under its own name (--no-deps keeps Qdrant up).
  docker compose -f "$QDRANT_COMPOSE" up -d --no-deps --force-recreate \
    acme-knowledge-seed >>/tmp/preflight-qdrant.log 2>&1
  END=$(( $(date +%s) + 360 ))
  until [ "$(date +%s)" -ge "$END" ]; do
    qdrant_points_ok && mcp_health_ok && break
    sleep 5
  done
  if qdrant_points_ok && mcp_health_ok; then
    fixd "acme_knowledge reseeded, MCP server healthy"
  else
    bad "knowledge base still not ready (see /tmp/preflight-qdrant.log; docker compose -f qdrant/docker-compose.yaml logs)"
  fi
fi

step "Broker WebSocket (cockpit path)"
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

check_dashboards() {  # ConfigMaps of $DASHBOARD_CMS present (apply if not)
  local cm
  for cm in "${DASHBOARD_CMS[@]}"; do
    if kubectl get cm -n "$SAM_NS" "$cm" >/dev/null 2>&1; then
      ok "Grafana dashboard ConfigMap $cm present"
    elif kubectl apply -f "$SCRIPT_DIR/observability/$cm.yaml" >/dev/null 2>&1; then
      fixd "dashboard ConfigMap $cm applied"
    else
      bad "dashboard $cm apply failed"
    fi
  done
}

eval_preruns() {  # every experiment in $EVAL_EXPERIMENTS has a completed run
  local exp EID DONE END
  if [ "$SKIP_EVALS" -eq 1 ]; then
    echo "   [SKIP]  eval pre-runs (--skip-evals)"
    return 0
  fi
  for exp in "${EVAL_EXPERIMENTS[@]}"; do
    EID=$(api GET /api/v1/platform/evaluations/experiments | id_of "$exp")
    if [ -z "$EID" ]; then bad "experiment '$exp' not on platform"; continue; fi
    if api GET "/api/v1/platform/evaluations/experiments/$EID/runs" \
        | grep -qE '"(completed|completed_with_warnings)"'; then
      ok "experiment '$exp' has a completed run"
    else
      echo "          fix: running '$exp' (this is the ~15-min part) ..."
      # Refresh the short-lived token right before the run; the
      # CLI does not refresh mid-run, so its polling can die with
      # a 401 while the run continues on the platform. The run is
      # the truth: after the CLI exits (either way), poll the
      # platform with a FRESH token for up to 12 min.
      (cd "$SCRIPT_DIR/eval" && "$SAM_CLI" config plan >/dev/null 2>&1) || true
      sam_auth_token >/dev/null 2>&1
      "$SAM_CLI" eval run "$exp" --url "$SAM_URL" 2>&1 \
        | tail -3 | sed 's/^/          /' || true
      # 20 min: the three-model benchmark alone is 36 LLM-judge calls
      # (measured 437 s on an idle platform, more on a busy one).
      DONE=0; END=$(( $(date +%s) + 1200 ))
      until [ "$(date +%s)" -ge "$END" ]; do
        (cd "$SCRIPT_DIR/eval" && "$SAM_CLI" config plan >/dev/null 2>&1) || true
        sam_auth_token >/dev/null 2>&1
        if api GET "/api/v1/platform/evaluations/experiments/$EID/runs" \
            | grep -qE '"(completed|completed_with_warnings)"'; then DONE=1; break; fi
        sleep 30
      done
      if [ "$DONE" -eq 1 ]; then
        fixd "experiment '$exp' pre-run completed"
      else
        bad "experiment '$exp' run did not complete (check the SAM UI)"
      fi
    fi
  done
}

if [ "$PROFILE" = "triage" ]; then

step "Grafana: dashboards, platform-DB datasource, grafana_ro grant"
check_dashboards
if kubectl get cm -n "$MON_NS" "$DATASOURCE_CM" >/dev/null 2>&1; then
  ok "datasource ConfigMap $DATASOURCE_CM present (ns $MON_NS)"
elif kubectl apply -f "$DATASOURCE_FILE" >/dev/null 2>&1; then
  fixd "datasource ConfigMap $DATASOURCE_CM applied"
else
  bad "datasource ConfigMap apply failed ($DATASOURCE_FILE)"
fi
if grant_ok; then
  ok "grafana_ro has SELECT on eval_runs in $PLATFORM_DB"
else
  echo "          fix: running grant-grafana-platform-db.sh ..."
  "$GRANT_SCRIPT" >/tmp/preflight-grant.log 2>&1
  if grant_ok; then fixd "grafana_ro granted SELECT on $PLATFORM_DB (log: /tmp/preflight-grant.log)"
  else bad "grant still missing (see /tmp/preflight-grant.log)"; fi
fi

step "Tempo traces (last 24 h, WARN only)"
NTR=$(tempo_trace_count)
if [ "${NTR:-0}" -ge 1 ] 2>/dev/null; then
  ok "Tempo has traces in the last 24 h (the claim's trace will land)"
else
  warn "no Tempo traces in the last 24 h -- broker tracing needs the OTel collector: (cd ../event-mesh-deployment && docker compose up -d otel-collector); the Grafana traces panel stays empty until then"
fi

step "Eval pre-runs"
eval_preruns

step "Dry fire ($FIRE_CLAIM via tools/fire-claim.js, warms the agents)"
if [ ! -f "$FIRE_JS" ]; then
  bad "tools/fire-claim.js missing in the checkout"
elif ! command -v node >/dev/null 2>&1; then
  bad "node not found (brew install node) -- cannot dry-fire"
else
  T0=$(date +%s)
  if node "$FIRE_JS" --claim "$FIRE_CLAIM" --wait "$FIRE_WAIT" \
      >/tmp/preflight-fire.log 2>&1; then
    DEC=$(grep -m1 -oE '"decision": *"[A-Z_]+"' /tmp/preflight-fire.log \
      | tr -d '" ' || true)
    ok "dry fire decided in $(( $(date +%s) - T0 )) s (${DEC:-decision printed}; log: /tmp/preflight-fire.log)"
  else
    tail -5 /tmp/preflight-fire.log | sed 's/^/          /'
    bad "dry fire failed or timed out after $(( $(date +%s) - T0 )) s -- see /tmp/preflight-fire.log (gwe receiver for fnol_received? external agent? model upstreams?)"
  fi
fi

else

step "Dashboard + eval pre-runs"
check_dashboards
eval_preruns

fi

echo ""
echo "== Manual reminders (not automatable)"
if [ "$PROFILE" = "triage" ]; then
  echo "   - Window A (sam_admin), tabs in order: Agent Management,"
  echo "     Workflows > Claim Triage, Claims Intake Liaison scrolled to"
  echo "     the allow list, Models, Grafana 'SAM Claims Governance',"
  echo "     Evaluations > Reports > ins-guardrails."
  echo "   - Window B (power_user, separate browser profile): Activities."
  echo "   - Window C: cockpit/index.html, always visible, LED green."
  echo "   - Links: ./demo-links.sh   Script: talk-track.md, Stage rules."
  echo "   - The dry fire warmed the agents; RESET the cockpit before"
  echo "     going live (the stage claim is CLM-0913-00001)."
  echo "   - Nothing runs live in Evaluations: beat 11 shows the"
  echo "     finished ins-guardrails report. Do not start a run on stage."
else
  echo "   - Windows: A sam_admin (Agent Management), B power_user"
  echo "     (Activities), C cockpit/extended.html (LED green), D Grafana."
  echo "   - Links: ./demo-links.sh"
  echo "   - Rehearsed break-glass buttons? RESET the cockpit after."
  echo "   - Builder Test tab works since 2.348.22 -- warm it up once after"
  echo "     any str restart (first test plan ~90 s, then ~4 s)."
fi
echo ""
echo "== Result: $PASS ok, $FIXED fixed, $WARNED warned, $FAILED failed"
if [ "$FAILED" -eq 0 ]; then
  echo "READY -- the demo environment is validated."
  exit 0
else
  echo "NOT READY -- resolve the [FAIL] items above."
  exit 1
fi
