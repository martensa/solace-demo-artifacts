#!/bin/bash
set -euo pipefail

# =============================================================
# install.sh -- layer the Acme Insurance demo onto a running
# agent-mesh-deployment (idempotent; safe to re-run).
# =============================================================
# Prerequisites (from agent-mesh-deployment, SAM 2.348.22):
#   ./scripts/setup-keycloak-client.sh + setup-keycloak-users.sh
#   ./scripts/load-images.sh && ./scripts/start.sh
#     start.sh runs ./scripts/provision.sh (RBAC, models,
#     max_tokens, developer-mcp); headless, run it afterwards:
#     ./scripts/provision.sh --login
#   sam auth login solace-lab --url https://sam.solace.lab
#
# Two PROFILES share the same core (steps 1-4) and differ in the
# overlay. Only one of them is on the platform at a time: both
# entrypoints subscribe to acmeins/claims/fnol/received/>, so the
# other profile's entrypoint is removed on install (mutual
# exclusion, both ways).
#
# Common steps (both profiles):
#   1. Host data stores: postgres+pgadmin (acme_insurance DB
#      seeded from postgres/), MongoDB acme-claims-mongo (port
#      27017) incl. first-run seed
#   2. Knowledge base: Qdrant + the Acme Claims Knowledge MCP
#      server (qdrant/, built locally, port 8765) incl. the
#      one-shot corpus seed (first run downloads the embedding
#      model -- allow up to 6 minutes)
#   3. The additional model aliases (idempotent re-apply of the
#      model step of provision.sh: the LiteLLM aliases plus
#      `google gemini`, skipped with a warning without its key).
#      They come before step 4 because the agents bind to them.
#   4. Insurance core package (core/: Insurance DB + Claims
#      Knowledge connectors, schema/guide skills, query experts;
#      expert model tier: fast for triage, general for --extended)
#
# TRIAGE profile (default, "Claim Triage in 30 Seconds"):
#   5. External agent: external-agent/ (Claims Intake Analyst, a
#      v1-SDK agent in ns sam-solace-lab-agents, discovered over
#      the broker) + wait for its agent card
#   6. Triage overlay (triage/): the Claims Intake Liaison and
#      Claims Triage Decision agents plus the claim-triage workflow
#      (its intake node targets the liaison, whose allow list names
#      exactly one peer -- the external analyst) via
#      `sam config apply`, then the claims-triage entrypoint
#      rendered from a template (the workflow RUNTIME name is
#      only known after the workflow exists) + receiver wait
#   7. Eval package (eval/: all datasets + experiments) and the
#      sam_admin evaluation watchlist
#   8. Dashboards: grafana_ro grant + platform-DB datasource
#      (agent-mesh-deployment) and both Grafana ConfigMaps
#
# EXTENDED profile (--extended, the event-driven acts):
#   5. Demo overlay (mesh/): Fast Lane Clerk, the three reporter/
#      planner agents, the three workflows and the claims-events
#      entrypoint -- the Storm Intake Analyst is created first
#      from fallback/ (workflow xref needs it), then removed
#      again unless --with-analyst (live Builder demo!)
#   6. Eval package (eval/, shared with the triage profile; its
#      triage-only ins-triage-decision experiment warns here)
#   7. Demo dashboard (Grafana ConfigMap)
#
#   ./install.sh                             # triage profile (default)
#   ./install.sh --extended                  # extended profile (old flow)
#   ./install.sh --extended --with-analyst   # + keep Storm Intake Analyst
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AMD="$REPO_DIR/agent-mesh-deployment"
SAM_URL="https://sam.solace.lab"
MONGO_COMPOSE="$SCRIPT_DIR/mongodb/docker-compose.yaml"
QDRANT_COMPOSE="$SCRIPT_DIR/qdrant/docker-compose.yaml"
MCP_HEALTH_URL="http://localhost:8765/health"
EXT_NS="sam-solace-lab-agents"
EXT_DEPLOY="sam-claims-intake-agent"
EXT_CARD="ClaimsIntakeAnalyst"
SAM_NS="sam-solace-lab"
GWE_DEPLOY="agent-mesh-solace-agent-mesh-gwe"

PROFILE=triage; WITH_ANALYST=0
for arg in "$@"; do
  case "$arg" in
    --extended)     PROFILE=extended ;;
    --with-analyst) WITH_ANALYST=1 ;;
    -h|--help)  grep '^#   \./' "$0" | sed 's/^#   //'; exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done
if [ "$WITH_ANALYST" -eq 1 ] && [ "$PROFILE" != "extended" ]; then
  echo "ERROR: --with-analyst only applies to the extended profile:" >&2
  echo "  ./install.sh --extended --with-analyst" >&2
  exit 1
fi
if [ "$PROFILE" = "triage" ]; then STEPS=8; else STEPS=7; fi

# --- Shared helpers (sam CLI + auth token) --------------------------
# shellcheck source=../agent-mesh-deployment/scripts/lib/common.sh
. "$AMD/scripts/lib/common.sh"
load_env "$AMD"
resolve_sam_cli
# The cached access token is short-lived; any real CLI call refreshes
# it via the stored refresh token (same trick as preflight/demo-links),
# so a stale cache does not 401 the raw curl calls below.
(cd "$SCRIPT_DIR/eval" && "$SAM_CLI" config plan >/dev/null 2>&1) || true
sam_auth_token

api() {  # api METHOD PATH -> body on stdout, code in API_CODE
  local method="$1" path="$2"
  # 2.348.22 pages every list endpoint (default 20 per page, newest
  # first): read the maximum page of 100 (the demos stay far below).
  [ "$method" = GET ] && case "$path" in *\?*) ;; *) path="$path?pageSize=100" ;; esac
  API_CODE=$(curl -sk -m 20 -X "$method" "$SAM_URL$path" \
    -H "Authorization: Bearer $SAM_AUTH_TOKEN" \
    -o /tmp/install-api-body.json -w "%{http_code}")
  cat /tmp/install-api-body.json 2>/dev/null || true
}
api_json() {  # api_json METHOD PATH JSON -> body on stdout, code in API_CODE
  local method="$1" path="$2" body="$3"
  API_CODE=$(curl -sk -m 20 -X "$method" "$SAM_URL$path" \
    -H "Authorization: Bearer $SAM_AUTH_TOKEN" \
    -H "Content-Type: application/json" -d "$body" \
    -o /tmp/install-api-body.json -w "%{http_code}")
  cat /tmp/install-api-body.json 2>/dev/null || true
}
id_of() {  # id_of PATH NAME -> platform id of the named resource ("" if absent)
  api GET "$1" | python3 -c "
import json,sys
try:
    for x in json.load(sys.stdin).get('data',[]):
        if x.get('name')==sys.argv[1]: print(x['id'])
except Exception: pass" "$2"
}
apply_pkg() {  # apply_pkg DIR -> filtered CLI output (warns on a non-zero exit)
  local dir="$1" rc=0
  (cd "$dir" && "$SAM_CLI" config apply) >/tmp/install-apply.log 2>&1 || rc=$?
  grep -viE "^time=" /tmp/install-apply.log \
    | grep -E "\+|~|=|\*|error|fail" | head -16 | sed 's/^/   /' || true
  [ "$rc" -ne 0 ] && echo "   WARNING: sam config apply in ${dir#"$SCRIPT_DIR/"} exited $rc (log: /tmp/install-apply.log)"
  return 0
}
remove_entrypoint() {  # remove_entrypoint NAME REASON... (no-op if absent)
  local name="$1" id; shift
  id=$(id_of /api/v1/platform/entrypoints "$name")
  [ -z "$id" ] && return 0
  echo "   removing entrypoint '$name' -- $*"
  api DELETE "/api/v1/platform/entrypoints/$id" >/dev/null
  echo "   '$name' deleted (HTTP $API_CODE)"
}

remove_resource() {  # remove_resource LABEL PATH NAME (no-op if absent)
  local label="$1" path="$2" name="$3" id
  id=$(id_of "$path" "$name")
  [ -z "$id" ] && return 0
  api DELETE "$path/$id" >/dev/null
  echo "   $label '$name' removed (HTTP $API_CODE)"
}

api GET /api/v1/platform/agents >/dev/null
if [ "${API_CODE:-}" != "200" ]; then
  echo "ERROR: platform API not reachable or token invalid" >&2
  echo "(HTTP $API_CODE). Log in first:" >&2
  echo "  sam auth login solace-lab --url $SAM_URL" >&2
  exit 1
fi

# Only ONE demo overlay runs at a time (shared host stores, one
# mongo on 27017, one stage). Refuse to install over another one.
OTHER_EPS=$(api GET /api/v1/platform/entrypoints | python3 -c "
import json,sys
for g in json.load(sys.stdin).get('data',[]):
    if g.get('name') in ('shop-events','plant-events'): print(g['name'])")
# entrypoint:demo-dir pairs (macOS bash 3.2: no associative arrays)
for pair in "shop-events:sam-retail-ops-demo" \
            "plant-events:sam-manufacturing-ops-demo"; do
  ep="${pair%%:*}"; dir="${pair#*:}"
  if grep -qxF "$ep" <<<"$OTHER_EPS"; then
    echo "ERROR: another demo overlay is installed (entrypoint" >&2
    echo "'$ep' found). Only one demo runs at a time." >&2
    echo "Remove it first:  (cd ../$dir && ./uninstall.sh)" >&2
    exit 1
  fi
done

echo "Profile: $PROFILE"
echo "== 1/$STEPS Host data stores"
for c in postgres pgadmin; do
  if [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" = "true" ]; then
    echo "   $c: running"
  else
    docker start "$c" >/dev/null && echo "   $c: started"
  fi
done
"$SCRIPT_DIR/postgres/seed.sh" | sed 's/^/  /'
# Only one demo's mongo runs at a time (all use standard 27017).
for other in retail-pos-mongo mfg-plant-mongo; do
  if [ "$(docker inspect -f '{{.State.Running}}' "$other" 2>/dev/null)" = "true" ]; then
    docker stop "$other" >/dev/null \
      && echo "   $other: stopped (port 27017 for acme-claims-mongo)"
  fi
done
docker compose -f "$MONGO_COMPOSE" up -d 2>&1 \
  | grep -viE "Running|Started" || true
echo "   acme-claims-mongo: up (seed runs only on first volume init)"

echo "== 2/$STEPS Knowledge base (qdrant/: Qdrant + MCP server + seed)"
# The MCP server image is built locally (first run: pip install of
# mcp/qdrant-client/fastembed, a few minutes). The one-shot seed
# service embeds qdrant/seed/documents.yaml into the acme_knowledge
# collection; fastembed downloads BAAI/bge-small-en-v1.5 once into
# the acme-knowledge-models volume. Both must be done before the
# core apply: the mcp/remote connector discovers its tools live.
qdrant_seed_state() {  # -> "<status> <exitcode>" of the seed container
  local cid
  cid=$(docker compose -f "$QDRANT_COMPOSE" ps -a -q acme-knowledge-seed \
    2>/dev/null | head -1 || true)
  [ -n "$cid" ] && docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' \
    "$cid" 2>/dev/null
  return 0
}
mcp_health_code() {  # -> HTTP code of GET /health ("000" = unreachable)
  local code
  code=$(curl -s -m 5 -o /dev/null -w '%{http_code}' "$MCP_HEALTH_URL" \
    2>/dev/null || true)
  echo "${code:-000}"
}
echo "   building + starting acme-knowledge (log: /tmp/install-qdrant-up.log) ..."
if ! docker compose -f "$QDRANT_COMPOSE" up -d --build \
    >/tmp/install-qdrant-up.log 2>&1; then
  tail -20 /tmp/install-qdrant-up.log | sed 's/^/   /'
  echo "ERROR: qdrant/ compose up failed (see /tmp/install-qdrant-up.log)" >&2
  exit 1
fi
echo "   waiting for the corpus seed (exit 0) and GET $MCP_HEALTH_URL == 200"
echo "   (first run downloads the embedding model; up to 6 minutes) ..."
READY=0; SEED_STATE=""; END=$(( $(date +%s) + 360 ))
until [ "$(date +%s)" -ge "$END" ]; do
  SEED_STATE=$(qdrant_seed_state)
  case "$SEED_STATE" in
    "exited 0") [ "$(mcp_health_code)" = "200" ] && { READY=1; break; } ;;
    exited\ *)  break ;;   # seed failed -> reported below
  esac
  sleep 5
done
if [ "$READY" -eq 1 ]; then
  echo "   acme-knowledge: seed done, MCP server healthy (HTTP 200)"
else
  echo "ERROR: knowledge base not ready after 6 min" >&2
  echo "(seed container: '${SEED_STATE:-not created}', MCP /health:" >&2
  echo "HTTP $(mcp_health_code)). Inspect with:" >&2
  echo "  docker compose -f qdrant/docker-compose.yaml logs acme-knowledge-seed acme-knowledge-mcp" >&2
  exit 1
fi

# Model tier of the two core experts, exported as INS_EXPERT_TIER
# (the core agents default it inline to "fast"; see core/manifest.yaml
# for why it is no manifest variable). The triage profile needs
# the policy and rules nodes back within seconds -> fast (Haiku 4.5;
# the model benchmark shows it matching general on the demo
# questions); the extended profile's long-form cohort analyses stay
# on general (Opus 4.8). An explicit INS_EXPERT_TIER=... ./install.sh
# still wins in both profiles. Re-running re-applies the same value.
EXPERT_TIER="${INS_EXPERT_TIER:-fast}"
[ "$PROFILE" = "extended" ] && EXPERT_TIER="${INS_EXPERT_TIER:-general}"
# The model aliases come FIRST: the core experts and the triage agents
# bind to an alias (fast / general) by name, and `sam config plan` does
# not validate that the alias exists -- on a fresh platform the agents
# would otherwise be created against an alias that is not there yet.
echo "== 3/$STEPS Model aliases (before the agents that bind to them)"
"$AMD/scripts/models/apply-models.sh" 2>&1 | tail -8

echo "== 4/$STEPS Insurance core (core/, expert tier: $EXPERT_TIER)"
# Through apply_pkg so a failing core apply is loud (WARNING + log),
# not swallowed -- a silent failure here surfaces much later as a
# cryptic xref error in the triage overlay. Note: the two experts show
# as "update" on every run (see the NOTE in core/agents/*.yaml).
export INS_EXPERT_TIER="$EXPERT_TIER"
apply_pkg "$SCRIPT_DIR/core"

# =============================================================
# TRIAGE profile
# =============================================================
if [ "$PROFILE" = "triage" ]; then

echo "== 5/$STEPS External agent (external-agent/ -> ns $EXT_NS)"
# The Claims Intake Analyst runs OUTSIDE the platform: a v1-SDK
# agent with its own runtime and model, reachable only through
# the broker. The platform discovers it via its agent card and
# lists it in Agent Management as type "discovered".
# Prerequisites NOT created here -- they are shared lab
# infrastructure from the companion repo solace-sam-artifacts
# (deploy/shared, `make apply-secrets`): the namespace and the secret
# `sam-shared-secret` that carries the broker URL, the LLM endpoint
# and key, and the S3 settings. Without them the apply fails or the
# pod crash-loops with no broker credentials, which would otherwise
# look like a slow card discovery further down.
for prereq in "namespace/$EXT_NS" "secret/sam-shared-secret -n $EXT_NS"; do
  # shellcheck disable=SC2086
  if ! kubectl get $prereq >/dev/null 2>&1; then
    echo "ERROR: prerequisite missing: $prereq" >&2
    echo "  It comes from the companion repo solace-sam-artifacts" >&2
    echo "  (deploy/shared; run 'make apply-secrets' there)." >&2
    exit 1
  fi
done
kubectl apply -f "$SCRIPT_DIR/external-agent/" | sed 's/^/   /'
if ! kubectl rollout status "deployment/$EXT_DEPLOY" -n "$EXT_NS" \
    --timeout=120s 2>&1 | sed 's/^/   /'; then
  echo "ERROR: $EXT_DEPLOY did not become ready in 120 s. Inspect:" >&2
  echo "  kubectl -n $EXT_NS describe deploy/$EXT_DEPLOY" >&2
  echo "  kubectl -n $EXT_NS logs deploy/$EXT_DEPLOY" >&2
  exit 1
fi
card_present() {  # -> exit 0 when the external card is in the mesh
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
echo "   waiting up to 90 s for the agent card '$EXT_CARD' (GET /api/v1/agentCards) ..."
CARD=0; END=$(( $(date +%s) + 90 ))
until [ "$(date +%s)" -ge "$END" ]; do
  if card_present; then CARD=1; break; fi
  sleep 5
done
if [ "$CARD" -eq 1 ]; then
  echo "   $EXT_CARD: discovered over the broker"
elif kubectl logs -n "$EXT_NS" "deploy/$EXT_DEPLOY" --tail=500 2>/dev/null \
    | grep -q "MongoDB Agent initialization completed successfully"; then
  echo "   $EXT_CARD: card not listed yet, but the pod log reports"
  echo "   'MongoDB Agent initialization completed successfully' --"
  echo "   discovery follows within the 10 s card interval; continuing"
else
  echo "   WARNING: $EXT_CARD neither discovered nor initialized after"
  echo "   90 s -- the intake node will fall back to 'intake unavailable'."
  echo "   Inspect:  kubectl -n $EXT_NS logs deploy/$EXT_DEPLOY"
  echo "   (preflight.sh re-checks the card; re-run install.sh after a fix)"
fi

echo "== 6/$STEPS Triage overlay (triage/: agents + workflow, then the entrypoint)"
# (a) Mutual exclusion: the extended profile's entrypoint listens on
#     the same FNOL topics and would answer the same event.
remove_entrypoint claims-events \
  "extended profile; it subscribes to the same acmeins/claims/fnol topics"
#     The extended overlay's agents and workflows are removed too, so
#     Agent Management shows the roster this demo talks about: four
#     platform agents plus the one discovered external analyst. Nothing
#     is lost -- './install.sh --extended' recreates them from mesh/.
for x in "Fast Lane Clerk" "Claims Incident Reporter" \
         "Storm Readiness Planner" "Fraud Case Reporter" \
         "Storm Intake Analyst"; do
  remove_resource "extended agent" /api/v1/platform/agents "$x"
done
for x in stalled-cohort-report storm-readiness cross-channel-fraud-report; do
  remove_resource "extended workflow" /api/v1/platform/workflows "$x"
done
#     And the extended profile's three MongoDB connectors. The claim of
#     this demo is that the PLATFORM never touches the intake store --
#     only the external analyst does -- and one click on the Connectors
#     page must not contradict it. ('--extended' recreates them.)
for x in fnol-intake scanner-results weather-cells; do
  remove_resource "extended connector" /api/v1/platform/connectors "$x"
done
# (b) Agents + workflow. Every workflow node targets a PLATFORM agent
#     (Query Expert, Claims Intake Liaison, Knowledge Expert, Claims
#     Triage Decision -- the external analyst is reached only through
#     the liaison, whose interAgentCommunication.allowList names
#     exactly that one peer), so the CLI xref check passes and the
#     whole overlay is declarative.
apply_pkg "$SCRIPT_DIR/triage"
# (c) The event-mesh entrypoint must target the workflow's RUNTIME
#     name (workflow_<id with - replaced by _>): with the plain
#     workflow name the gateway publishes to a topic nobody listens
#     on (2.225.14, still in 2.348.22 -- re-verified 2026-09-21; see
#     the README). The id exists only after (b), so the entrypoint
#     is rendered from a template now.
WF_ID=$(id_of /api/v1/platform/workflows claim-triage)
if [ -z "$WF_ID" ]; then
  echo "ERROR: workflow 'claim-triage' not on the platform after the" >&2
  echo "triage/ apply -- see /tmp/install-apply.log" >&2
  exit 1
fi
WF_RUNTIME="workflow_${WF_ID//-/_}"
RENDERED="$SCRIPT_DIR/triage/.rendered"
TPL_DIR="$SCRIPT_DIR/triage/entrypoints"
for tpl in manifest.yaml.template claims-triage.yaml.template; do
  if [ ! -f "$TPL_DIR/$tpl" ]; then
    echo "ERROR: template $TPL_DIR/$tpl missing" >&2; exit 1
  fi
done
rm -rf "$RENDERED"
mkdir -p "$RENDERED/entrypoints"
sed "s/__WORKFLOW_RUNTIME__/$WF_RUNTIME/g" "$TPL_DIR/manifest.yaml.template" \
  > "$RENDERED/manifest.yaml"
sed "s/__WORKFLOW_RUNTIME__/$WF_RUNTIME/g" "$TPL_DIR/claims-triage.yaml.template" \
  > "$RENDERED/entrypoints/claims-triage.yaml"
echo "   rendered claims-triage entrypoint -> targetWorkflowName $WF_RUNTIME"
echo "   (triage/.rendered/, git-ignored)"
apply_pkg "$RENDERED"
# (d) Receivers come up about a second after the deploy on 2.348.22
#     (2.225.14: 20-40 s); events published before that are LOST
#     (no queue yet). The wait stays as a guard.
echo "   waiting up to 60 s for the gwe receiver of rule fnol_received ..."
RCV=0; END=$(( $(date +%s) + 60 ))
until [ "$(date +%s)" -ge "$END" ]; do
  if kubectl logs -n "$SAM_NS" "deploy/$GWE_DEPLOY" -c gwe --since=90s \
      2>/dev/null | grep "persistent receiver started" \
      | grep -q "fnol_received"; then
    RCV=1; break
  fi
  sleep 5
done
if [ "$RCV" -eq 1 ]; then
  echo "   gwe: persistent receiver started for fnol_received (events are"
  echo "   picked up from now on)"
else
  echo "   NOTE: no fresh 'persistent receiver started ... fnol_received'"
  echo "   line in the gwe log of the last 90 s. On a re-run with an"
  echo "   unchanged entrypoint that is expected (no redeploy); otherwise"
  echo "   check:  kubectl -n $SAM_NS logs deploy/$GWE_DEPLOY -c gwe | grep fnol_received"
  echo "   preflight.sh's dry fire is the real end-to-end check."
fi

echo "== 7/$STEPS Eval package + watchlist"
apply_pkg "$SCRIPT_DIR/eval"
# The watchlist is per user (the CLI token user = sam_admin) and
# holds at most 5 agents: the three agents of this demo that
# actually reason. The Claims Intake Liaison is left out (it only
# carries the hop across the platform boundary) and the Claims
# Intake Analyst is external -- it has no platform record at all.
api_json PUT /api/v1/platform/evaluations/watchlist \
  '{"agentNames":["Acme Insurance Query Expert","Acme Claims Knowledge Expert","Claims Triage Decision"]}' \
  >/dev/null
echo "   watchlist PUT -> HTTP $API_CODE (sam_admin: Query Expert, Knowledge"
echo "   Expert, Claims Triage Decision)"
echo "   NOTE: experiments have no runs yet on a fresh platform --"
echo "   pre-run before the demo (~15 min): ./preflight.sh does it"
echo "   automatically (the bare 'sam eval run' needs the token"
echo "   exported -- see scripts/lib/common.sh sam_auth_token)."

echo "== 8/$STEPS Dashboards (Grafana)"
# The governance dashboard reads the PLATFORM DB (agents, RBAC,
# eval runs) through a second datasource; grafana_ro has no SELECT
# there by default -> idempotent grant + datasource ConfigMap.
if ! "$AMD/scripts/observability/grant-grafana-platform-db.sh" 2>&1 | sed 's/^/   /'; then
  echo "   WARNING: grant-grafana-platform-db.sh failed -- the governance"
  echo "   dashboard's platform-DB panels stay empty; preflight.sh re-checks"
  echo "   and re-runs the grant."
fi
kubectl apply -f "$SCRIPT_DIR/observability/dashboard-sam-claims-governance.yaml" \
  | sed 's/^/   /'
kubectl apply -f "$SCRIPT_DIR/observability/dashboard-sam-insurance-ops.yaml" \
  | sed 's/^/   /'

echo ""
echo "Done (triage profile). Stage: cockpit/index.html -- run ./preflight.sh"
echo "before going live (~15 min: eval pre-runs + one dry fire that warms"
echo "the agents)."

# =============================================================
# EXTENDED profile
# =============================================================
else

echo "== 5/$STEPS Demo overlay (mesh/)"
# Mutual exclusion: the triage profile's entrypoint listens on the
# same FNOL topics. The external Claims Intake Analyst (ns
# sam-solace-lab-agents) is NOT removed here: it is harmless on the
# extended stage (a discovered agent nothing references) and
# uninstall.sh takes it down.
remove_entrypoint claims-triage \
  "triage profile; it subscribes to the same acmeins/claims/fnol topics"
# The workflows xref-validate against the Storm Intake Analyst ->
# ensure it exists BEFORE the mesh apply (create from fallback if
# missing).
SIA_ID=$(api GET /api/v1/platform/agents | python3 -c "
import json,sys
for a in json.load(sys.stdin).get('data',[]):
    if a['name']=='Storm Intake Analyst': print(a['id'])")
if [ -z "$SIA_ID" ]; then
  echo "   Storm Intake Analyst missing -> creating from fallback/"
  (cd "$SCRIPT_DIR/fallback" && "$SAM_CLI" config apply 2>&1 \
    | grep -viE "^time=" | grep -E "\+|~|\*|error" | head -8)
fi
(cd "$SCRIPT_DIR/mesh" && "$SAM_CLI" config apply 2>&1 \
  | grep -viE "^time=" | grep -E "\+|~|\*|error|fail" | head -16)

if [ "$WITH_ANALYST" -eq 0 ]; then
  # The three MongoDB connectors STAY installed (workplace
  # infrastructure, like the postgres/MCP connectors): the live
  # Builder beat only creates the AGENT binding them -- one
  # config, no connector sub-tasks, no cross-component
  # validation (optimization inherited from the mfg demo; the
  # Builder's connector-validation deadlock behind it is
  # 2.225.14, still the case on 2.348.22 -- re-verified
  # 2026-09-21).
  echo "   removing Storm Intake Analyst (live Builder demo; connectors stay)"
  SIA_ID=$(api GET /api/v1/platform/agents | python3 -c "
import json,sys
for a in json.load(sys.stdin).get('data',[]):
    if a['name']=='Storm Intake Analyst': print(a['id'])")
  [ -n "$SIA_ID" ] && api DELETE "/api/v1/platform/agents/$SIA_ID" >/dev/null \
    && echo "   Storm Intake Analyst deleted (HTTP $API_CODE)"
else
  echo "   keeping Storm Intake Analyst (--with-analyst)"
fi

echo "== 6/$STEPS Eval package"
# The package is shared with the triage profile. Its
# ins-triage-decision experiment targets the Claims Triage Decision
# agent, which only the triage overlay installs -- on an
# extended-only platform that one resource cannot apply. apply_pkg
# reports the non-zero exit and continues, so the dashboard step
# below still runs.
apply_pkg "$SCRIPT_DIR/eval"
echo "   NOTE: experiments have no runs yet on a fresh platform --"
echo "   pre-run before the demo (~15 min): ./preflight.sh does it"
echo "   automatically (the bare 'sam eval run' needs the token"
echo "   exported -- see scripts/lib/common.sh sam_auth_token)."

echo "== 7/$STEPS Demo dashboard"
kubectl apply -f "$SCRIPT_DIR/observability/dashboard-sam-insurance-ops.yaml"

echo ""
echo "Done (extended profile). Stage: cockpit/extended.html -- run"
echo "./preflight.sh before going live (models probe, kyverno/monitoring"
echo "health, cockpit LED, eval pre-runs)."

fi
