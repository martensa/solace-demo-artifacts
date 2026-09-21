#!/bin/bash
set -euo pipefail

# =============================================================
# uninstall.sh -- remove the Acme Insurance demo (BOTH profiles)
# from the platform, leaving the SAM infrastructure in
# agent-mesh-deployment (models, RBAC, developer-mcp,
# observability) untouched (idempotent; absent resources are
# skipped silently).
# =============================================================
# Removes the TRIAGE overlay (claims-triage entrypoint,
# claim-triage workflow, the Claims Intake Liaison and the Claims
# Triage Decision agent, the external Claims Intake Analyst in ns
# sam-solace-lab-agents via `kubectl delete -f external-agent/`,
# the rendered entrypoint dir triage/.rendered), the EXTENDED
# overlay (claims-events entrypoint, stalled-cohort-report +
# storm-readiness + cross-channel-fraud-report workflows, Claims
# Incident Reporter, Storm Readiness Planner, Fraud Case
# Reporter, Fast Lane Clerk, Storm Intake Analyst +
# fnol-intake/weather-cells/scanner-results connectors), the
# insurance CORE (the two Acme experts, their connectors and
# skills), eval experiments + datasets of both profiles
# (INCLUDING their run history!), the sam_admin evaluation
# watchlist install.sh set, and both demo dashboards.
# The demo mongo container is removed INCLUDING its volume: the
# data volume is anonymous and re-seeded from mongodb/seed on
# every fresh `install.sh` anyway, so keeping it would only leave
# a dangling volume behind. The knowledge base stack (Qdrant +
# MCP server) goes the same way INCLUDING its named volumes
# (acme-knowledge-data AND the acme-knowledge-models embedding
# cache -- the next install.sh downloads the model again).
# Keeps: the 5 model aliases, RBAC, the developer-mcp entrypoint,
# the grafana_ro grant + platform-DB datasource (infrastructure,
# agent-mesh-deployment), the shared host containers
# postgres/pgadmin (acme_insurance stays seeded unless
# --purge-data; install.sh re-seeds it).
#
# Also SURVIVES, by design, and nowhere else documented: the demo's
# HISTORY. Chat sessions and tasks stay in the webui and orchestrator
# databases (they outlive the agents they name), and the artifacts of
# every agent run stay in the SeaweedFS bucket sam-solace-lab under
# <user>/<session>/. That is deliberate -- it is what makes a
# post-mortem possible after a demo is gone -- but it means an
# uninstall does NOT reclaim that space. The one exception is the
# evaluation RUN artifacts below, which this script does delete,
# because the header above promises to remove the run history and
# leaving the objects behind would make that promise half true.
#
#   ./uninstall.sh               # remove both overlays + insurance core
#   ./uninstall.sh --keep-core   # overlays only (fast demo switch)
#   ./uninstall.sh --dry-run     # show what would be removed
#   ./uninstall.sh --purge-data  # also DROP the acme_insurance DB
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AMD="$REPO_DIR/agent-mesh-deployment"
SAM_URL="https://sam.solace.lab"
EXT_DIR="$SCRIPT_DIR/external-agent"
RENDERED="$SCRIPT_DIR/triage/.rendered"
DASHBOARD_CMS="dashboard-sam-claims-governance dashboard-sam-insurance-ops"

DRY=0; KEEP_CORE=0; PURGE=0
for arg in "$@"; do
  case "$arg" in
    --dry-run)    DRY=1 ;;
    --keep-core)  KEEP_CORE=1 ;;
    --purge-data) PURGE=1 ;;
    -h|--help)    grep '^#   \./' "$0" | sed 's/^#   //'; exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

# shellcheck source=../agent-mesh-deployment/scripts/lib/common.sh
. "$AMD/scripts/lib/common.sh"
load_env "$AMD"
resolve_sam_cli >/dev/null 2>&1 || true
# The cached access token is short-lived; any real CLI call refreshes
# it via the stored refresh token (same trick as preflight/demo-links),
# so a stale cache does not 401 the raw curl calls below.
(cd "$SCRIPT_DIR/eval" && "${SAM_CLI:-sam}" config plan >/dev/null 2>&1) || true
sam_auth_token

api() {
  local method="$1" path="$2"
  API_CODE=$(curl -sk -m 20 -X "$method" "$SAM_URL$path" \
    -H "Authorization: Bearer $SAM_AUTH_TOKEN" \
    -o /tmp/uninstall-api-body.json -w "%{http_code}")
  cat /tmp/uninstall-api-body.json 2>/dev/null || true
}
api_json() {  # api_json METHOD PATH JSON -> body on stdout, code in API_CODE
  local method="$1" path="$2" body="$3"
  API_CODE=$(curl -sk -m 20 -X "$method" "$SAM_URL$path" \
    -H "Authorization: Bearer $SAM_AUTH_TOKEN" \
    -H "Content-Type: application/json" -d "$body" \
    -o /tmp/uninstall-api-body.json -w "%{http_code}")
  cat /tmp/uninstall-api-body.json 2>/dev/null || true
}

find_id() {  # find_id PATH NAME
  api GET "$1" | python3 -c "
import json,sys
for x in json.load(sys.stdin).get('data',[]):
    if x.get('name')==sys.argv[1]: print(x['id'])" "$2" 2>/dev/null
}

remove() {  # remove LABEL PATH NAME
  local label="$1" path="$2" name="$3" id
  id=$(find_id "$path" "$name")
  if [ -z "$id" ]; then
    echo "   $label '$name': not present"
  elif [ "$DRY" -eq 1 ]; then
    echo "   $label '$name': WOULD delete ($id)"
  else
    api DELETE "$path/$id" >/dev/null
    echo "   $label '$name': deleted (HTTP $API_CODE)"
  fi
}

api GET /api/v1/platform/agents >/dev/null
if [ "${API_CODE:-}" != "200" ]; then
  echo "ERROR: platform API not reachable or token invalid (HTTP $API_CODE)." >&2
  echo "  sam auth login solace-lab --url $SAM_URL" >&2
  exit 1
fi

# Order: entrypoints first (stops event intake), then workflows,
# then agents, then connectors -- for both profiles.
echo "== Entrypoints (stop event intake first)"
remove "entrypoint" /api/v1/platform/entrypoints      "claims-triage"
remove "entrypoint" /api/v1/platform/entrypoints      "claims-events"

echo "== Triage overlay (triage/ + external agent)"
remove "workflow"   /api/v1/platform/workflows     "claim-triage"
# Both triage agents are platform records (triage/manifest.yaml):
# the liaison is the only agent allowed to delegate to the external
# Claims Intake Analyst (its interAgentCommunication.allowList), the
# decision agent writes the schema-bound triage verdict.
remove "agent"      /api/v1/platform/agents        "Claims Intake Liaison"
remove "agent"      /api/v1/platform/agents        "Claims Triage Decision"
if [ ! -d "$EXT_DIR" ]; then
  echo "   external agent: external-agent/ not in the checkout, skipped"
elif [ "$DRY" -eq 1 ]; then
  echo "   external agent: WOULD run: kubectl delete -f external-agent/ --ignore-not-found"
else
  kubectl delete -f "$EXT_DIR/" --ignore-not-found 2>&1 | sed 's/^/   /' || true
fi
if [ -d "$RENDERED" ]; then
  if [ "$DRY" -eq 1 ]; then echo "   WOULD remove triage/.rendered/"
  else rm -rf "$RENDERED" && echo "   triage/.rendered/ removed"; fi
else
  echo "   triage/.rendered/: not present"
fi

echo "== Extended overlay (mesh/ + fallback/)"
remove "workflow"   /api/v1/platform/workflows     "stalled-cohort-report"
remove "workflow"   /api/v1/platform/workflows     "storm-readiness"
remove "workflow"   /api/v1/platform/workflows     "cross-channel-fraud-report"
remove "agent"      /api/v1/platform/agents        "Claims Incident Reporter"
remove "agent"      /api/v1/platform/agents        "Storm Readiness Planner"
remove "agent"      /api/v1/platform/agents        "Fraud Case Reporter"
remove "agent"      /api/v1/platform/agents        "Fast Lane Clerk"
remove "agent"      /api/v1/platform/agents        "Storm Intake Analyst"
remove "connector"  /api/v1/platform/connectors    "fnol-intake"
remove "connector"  /api/v1/platform/connectors    "weather-cells"
remove "connector"  /api/v1/platform/connectors    "scanner-results"

if [ "$KEEP_CORE" -eq 0 ]; then
  echo "== Insurance core"
  remove "agent"      /api/v1/platform/agents      "Acme Insurance Query Expert"
  remove "agent"      /api/v1/platform/agents      "Acme Claims Knowledge Expert"
  remove "connector"  /api/v1/platform/connectors  "Acme Insurance DB"
  remove "connector"  /api/v1/platform/connectors  "Acme Claims Knowledge"
  remove "skill"      /api/v1/platform/skills      "acme-insurance-schema"
  remove "skill"      /api/v1/platform/skills      "acme-knowledge-guide"
else
  echo "== Insurance core: kept (--keep-core)"
fi

echo "== Evaluation (deletes run history too!)"
# Collect the run ids BEFORE the experiments go: deleting an experiment
# cascades its eval_runs rows away, and without the ids the artifacts
# those runs wrote in the object store can no longer be attributed.
EVAL_RUN_IDS=""
for exp in ins-ops-quality ins-ops-model-benchmark ins-claims-rules \
           ins-triage-decision ins-guardrails; do
  eid=$(find_id /api/v1/platform/evaluations/experiments "$exp")
  [ -z "$eid" ] && continue
  EVAL_RUN_IDS="$EVAL_RUN_IDS $(api GET \
    "/api/v1/platform/evaluations/experiments/$eid/runs" | python3 -c "
import json,sys
try: print(' '.join(r['id'] for r in json.load(sys.stdin).get('data',[])))
except Exception: pass" 2>/dev/null)"
done
remove "experiment" /api/v1/platform/evaluations/experiments "ins-ops-quality"
remove "experiment" /api/v1/platform/evaluations/experiments "ins-ops-model-benchmark"
remove "experiment" /api/v1/platform/evaluations/experiments "ins-claims-rules"
remove "experiment" /api/v1/platform/evaluations/experiments "ins-triage-decision"
remove "experiment" /api/v1/platform/evaluations/experiments "ins-guardrails"
remove "dataset"    /api/v1/platform/evaluations/datasets    "ins-ops-questions"
remove "dataset"    /api/v1/platform/evaluations/datasets    "ins-claims-rules"
remove "dataset"    /api/v1/platform/evaluations/datasets    "ins-triage-decisions"
remove "dataset"    /api/v1/platform/evaluations/datasets    "ins-guardrails"
# install.sh (step 7) puts the three reasoning agents of this demo on
# the evaluation watchlist of the CLI token user (sam_admin). It is a
# per-user setting, not a resource, so nothing above touches it --
# clear it here, or the Evaluations page keeps watching agents that
# no longer exist.
if [ "$DRY" -eq 1 ]; then
  echo "   watchlist (sam_admin): WOULD clear"
else
  api_json PUT /api/v1/platform/evaluations/watchlist \
    '{"agentNames":[]}' >/dev/null
  echo "   watchlist (sam_admin): cleared (HTTP $API_CODE)"
fi

# The run rows are gone; their artifacts are not. SeaweedFS keeps
# /buckets/sam-solace-lab/sam-solace-lab/eval/runs/<run id>/ per run
# (about 1 MB each), and nothing on the platform references them any
# more. Remove exactly the ids collected above -- never the whole
# eval/runs prefix, which other demos share.
# `grep` exits 1 when there is nothing to match, and under `set -e` a
# bare assignment would take the script down with it.
EVAL_RUN_IDS=$(echo "$EVAL_RUN_IDS" | tr ' ' '\n' \
  | grep -E '^[0-9a-f-]{36}$' | sort -u || true)
if [ -z "$EVAL_RUN_IDS" ]; then
  echo "   eval run artifacts: none to remove"
elif [ "$DRY" -eq 1 ]; then
  echo "   eval run artifacts: WOULD remove $(echo "$EVAL_RUN_IDS" | wc -l | tr -d ' ') run dir(s) from SeaweedFS"
elif ! kubectl get pod -n sam-solace-lab agent-mesh-seaweedfs-0 >/dev/null 2>&1; then
  echo "   eval run artifacts: SKIPPED (seaweedfs pod not reachable)"
else
  # One `weed shell` per path on purpose: piping several fs.rm commands
  # into one shell session silently drops all but the first (verified
  # 2026-09-20 -- 8 paths in, 1 removed, no error for the other 7).
  SW_BASE=/buckets/sam-solace-lab/sam-solace-lab
  SW_RUNNER=$(kubectl exec -n sam-solace-lab agent-mesh-seaweedfs-0 -- sh -c \
    "echo 'fs.ls $SW_BASE/eval-runner' | weed shell" 2>/dev/null \
    | awk '{print $NF}' || true)
  for rid in $EVAL_RUN_IDS; do
    kubectl exec -n sam-solace-lab agent-mesh-seaweedfs-0 -- sh -c \
      "echo 'fs.rm -rf $SW_BASE/eval/runs/$rid' | weed shell" >/dev/null 2>&1 || true
    # The per-example tool outputs of the same run live next door under
    # eval-runner/eval-<run id>-<example id>-0. Those are exactly
    # attributable; their sibling task dirs (a bare task uuid) are not,
    # and are deliberately left rather than matched on a timestamp
    # prefix that another demo's run could share.
    for d in $SW_RUNNER; do
      case "$d" in
        eval-"$rid"-*)
          kubectl exec -n sam-solace-lab agent-mesh-seaweedfs-0 -- sh -c \
            "echo 'fs.rm -rf $SW_BASE/eval-runner/$d' | weed shell" >/dev/null 2>&1 || true ;;
      esac
    done
  done
  echo "   eval run artifacts: removed $(echo "$EVAL_RUN_IDS" | wc -l | tr -d ' ') run dir(s) from SeaweedFS"
fi

echo "== Demo dashboards"
for cm in $DASHBOARD_CMS; do
  if [ "$DRY" -eq 1 ]; then
    kubectl get cm -n sam-solace-lab "$cm" >/dev/null 2>&1 \
      && echo "   WOULD delete ConfigMap $cm" \
      || echo "   dashboard $cm: not present"
  else
    kubectl delete cm -n sam-solace-lab "$cm" \
      --ignore-not-found | sed 's/^/   /'
  fi
done

# The data stacks belong to the CORE: --keep-core is the fast switch
# between the two profiles, and both profiles read the same Mongo store
# and the same knowledge base. Tearing them down there would leave the
# kept core connectors pointing at an empty Qdrant, and make the next
# install re-download the embedding model (up to 6 minutes).
if [ "$KEEP_CORE" -eq 1 ]; then
  echo "== MongoDB + knowledge base: kept (--keep-core; the core reads them)"
else
  echo "== MongoDB (container + anonymous volume)"
  if [ "$DRY" -eq 1 ]; then
    echo "   WOULD run: docker compose -f mongodb/docker-compose.yaml down -v"
  else
    docker compose -f "$SCRIPT_DIR/mongodb/docker-compose.yaml" down -v 2>&1 \
      | sed 's/^/   /' || true
  fi

  echo "== Knowledge base (Qdrant + MCP server + data/model volumes)"
  if [ "$DRY" -eq 1 ]; then
    echo "   WOULD run: docker compose -f qdrant/docker-compose.yaml down -v"
  else
    docker compose -f "$SCRIPT_DIR/qdrant/docker-compose.yaml" down -v 2>&1 \
      | sed 's/^/   /' || true
  fi
fi

if [ "$PURGE" -eq 1 ]; then
  echo "== Postgres database (--purge-data)"
  for db in acme_insurance; do
    if [ "$DRY" -eq 1 ]; then
      echo "   WOULD drop database $db"
    else
      docker exec postgres psql -U postgres -q -c \
        "DROP DATABASE IF EXISTS $db;" \
        && echo "   $db: dropped" || echo "   $db: drop failed"
    fi
  done
fi

rm -f /tmp/uninstall-api-body.json

echo ""
if [ "$DRY" -eq 1 ]; then
  echo "Dry run - nothing was changed."
elif [ "$KEEP_CORE" -eq 1 ]; then
  echo "Demo overlays removed (triage + extended). Insurance core, models,"
  echo "RBAC and the platform infrastructure stay."
else
  echo "Demo removed (both overlays + insurance core). Models, RBAC,"
  echo "developer-mcp and the platform infrastructure stay."
fi
