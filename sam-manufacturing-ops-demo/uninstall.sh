#!/bin/bash
set -euo pipefail

# =============================================================
# uninstall.sh -- remove the Event-Driven Manufacturing Ops demo
# from the platform, leaving the SAM infrastructure in
# agent-mesh-deployment (models, RBAC, developer-mcp,
# observability) untouched (idempotent; absent resources are
# skipped silently).
# =============================================================
# Removes the demo OVERLAY (plant-events entrypoint,
# quality-incident-report + supply-replenishment workflows,
# Quality Incident Reporter, Supply Chain Watcher, Production
# Confirmation Clerk, Shop Floor Analyst +
# mfg-telemetry/mfg-consumption connectors), the manufacturing
# CORE (the four Acme query experts, their connectors and schema
# skills), eval experiments + dataset (INCLUDING their run
# history!) and the demo dashboard.
# The demo mongo container is removed INCLUDING its volume: the
# data volume is anonymous and re-seeded from mongodb/seed on
# every fresh `install.sh` anyway, so keeping it would only leave
# a dangling volume behind.
# Keeps: the 5 model aliases, RBAC, the developer-mcp entrypoint,
# the shared host containers postgres/pgadmin (mfg_* DBs stay
# seeded unless --purge-data; install.sh re-seeds them).
#
#   ./uninstall.sh               # remove overlay + mfg core
#   ./uninstall.sh --keep-core   # overlay only (fast demo switch)
#   ./uninstall.sh --dry-run     # show what would be removed
#   ./uninstall.sh --purge-data  # also DROP the mfg_* postgres DBs
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AMD="$REPO_DIR/agent-mesh-deployment"
SAM_URL="https://sam.solace.lab"

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
sam_auth_token

api() {
  local method="$1" path="$2"
  API_CODE=$(curl -sk -m 20 -X "$method" "$SAM_URL$path" \
    -H "Authorization: Bearer $SAM_AUTH_TOKEN" \
    -o /tmp/uninstall-api-body.json -w "%{http_code}")
  cat /tmp/uninstall-api-body.json 2>/dev/null || true
}

find_id() {  # find_id PATH NAME
  api GET "$1" | python3 -c "
import json,sys
for x in json.load(sys.stdin).get('data',[]):
    if x.get('name')=='$2': print(x['id'])" 2>/dev/null
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

echo "== Demo overlay"
# Order: entrypoint first (stops event intake), then workflows,
# then agents, then connectors.
remove "entrypoint" /api/v1/platform/gateways      "plant-events"
remove "workflow"   /api/v1/platform/workflows     "quality-incident-report"
remove "workflow"   /api/v1/platform/workflows     "supply-replenishment"
remove "agent"      /api/v1/platform/agents        "Quality Incident Reporter"
remove "agent"      /api/v1/platform/agents        "Supply Chain Watcher"
remove "agent"      /api/v1/platform/agents        "Production Confirmation Clerk"
remove "agent"      /api/v1/platform/agents        "Shop Floor Analyst"
remove "connector"  /api/v1/platform/connectors    "mfg-telemetry"
remove "connector"  /api/v1/platform/connectors    "mfg-consumption"

if [ "$KEEP_CORE" -eq 0 ]; then
  echo "== Manufacturing core"
  remove "agent"      /api/v1/platform/agents      "Acme CRM Query Expert"
  remove "agent"      /api/v1/platform/agents      "Acme OMS Query Expert"
  remove "agent"      /api/v1/platform/agents      "Acme PDM Query Expert"
  remove "agent"      /api/v1/platform/agents      "Acme SCM Query Expert"
  remove "connector"  /api/v1/platform/connectors  "Acme CRM DB"
  remove "connector"  /api/v1/platform/connectors  "Acme OMS DB"
  remove "connector"  /api/v1/platform/connectors  "Acme PDM DB"
  remove "connector"  /api/v1/platform/connectors  "Acme SCM DB"
  remove "skill"      /api/v1/platform/skills      "mfg-crm-schema"
  remove "skill"      /api/v1/platform/skills      "mfg-oms-schema"
  remove "skill"      /api/v1/platform/skills      "mfg-pdm-schema"
  remove "skill"      /api/v1/platform/skills      "mfg-scm-schema"
else
  echo "== Manufacturing core: kept (--keep-core)"
fi

echo "== Evaluation (deletes run history too!)"
remove "experiment" /api/v1/platform/evaluations/experiments "mfg-ops-quality"
remove "experiment" /api/v1/platform/evaluations/experiments "mfg-ops-model-benchmark"
remove "dataset"    /api/v1/platform/evaluations/datasets    "mfg-ops-questions"

echo "== Demo dashboard"
if [ "$DRY" -eq 1 ]; then
  kubectl get cm -n sam-solace-lab dashboard-sam-mfg-ops >/dev/null 2>&1 \
    && echo "   WOULD delete ConfigMap dashboard-sam-mfg-ops" \
    || echo "   dashboard: not present"
else
  kubectl delete cm -n sam-solace-lab dashboard-sam-mfg-ops \
    --ignore-not-found | sed 's/^/   /'
fi

echo "== MongoDB (container + anonymous volume)"
if [ "$DRY" -eq 1 ]; then
  echo "   WOULD run: docker compose -f mongodb/docker-compose.yaml down -v"
else
  docker compose -f "$SCRIPT_DIR/mongodb/docker-compose.yaml" down -v 2>&1 \
    | sed 's/^/   /' || true
fi

if [ "$PURGE" -eq 1 ]; then
  echo "== Postgres databases (--purge-data)"
  for db in mfg_crm mfg_oms mfg_pdm mfg_scm; do
    if [ "$DRY" -eq 1 ]; then
      echo "   WOULD drop database $db"
    else
      docker exec postgres psql -U postgres -q -c \
        "DROP DATABASE IF EXISTS $db;" \
        && echo "   $db: dropped" || echo "   $db: drop failed"
    fi
  done
fi

echo ""
if [ "$DRY" -eq 1 ]; then
  echo "Dry run - nothing was changed."
elif [ "$KEEP_CORE" -eq 1 ]; then
  echo "Demo overlay removed. Manufacturing core, models, RBAC and"
  echo "the platform infrastructure stay."
else
  echo "Demo removed (overlay + manufacturing core). Models, RBAC,"
  echo "developer-mcp and the platform infrastructure stay."
fi
