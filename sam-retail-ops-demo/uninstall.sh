#!/bin/bash
set -euo pipefail

# =============================================================
# uninstall.sh -- remove the Event-Driven Retail Ops demo from
# the platform, leaving agent-mesh-deployment's core untouched
# (idempotent; absent resources are skipped silently).
# =============================================================
# Removes: shop-events entrypoint, order-incident-report
# workflow, Order Incident Reporter, Order Confirmation Clerk,
# Retail POS Analyst + retail-poslog connector, eval experiments
# + dataset (INCLUDING their run history!), the demo dashboard.
# Keeps: retail core (connectors/skills/experts/360/developer-
# mcp), the 5 model aliases, host containers (mongo stays up;
# use --purge-data to also remove the mongo container + volume).
#
#   ./uninstall.sh               # remove platform resources
#   ./uninstall.sh --dry-run     # show what would be removed
#   ./uninstall.sh --purge-data  # also mongo container + volume
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AMD="$REPO_DIR/agent-mesh-deployment"
SAM_URL="https://sam.solace.lab"

DRY=0; PURGE=0
for arg in "$@"; do
  case "$arg" in
    --dry-run)    DRY=1 ;;
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

find_id() {  # find_id PATH NAME [KEY]
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

echo "== Platform resources"
# Order: entrypoint first (stops event intake), then workflow,
# then agents, then connector.
remove "entrypoint" /api/v1/platform/gateways      "shop-events"
remove "workflow"   /api/v1/platform/workflows     "order-incident-report"
remove "agent"      /api/v1/platform/agents        "Order Incident Reporter"
remove "agent"      /api/v1/platform/agents        "Order Confirmation Clerk"
remove "agent"      /api/v1/platform/agents        "Retail POS Analyst"
remove "connector"  /api/v1/platform/connectors    "retail-poslog"

echo "== Evaluation (deletes run history too!)"
remove "experiment" /api/v1/platform/evaluations/experiments "retail-ops-quality"
remove "experiment" /api/v1/platform/evaluations/experiments "retail-ops-model-benchmark"
remove "dataset"    /api/v1/platform/evaluations/datasets    "retail-ops-questions"

echo "== Demo dashboard"
if [ "$DRY" -eq 1 ]; then
  kubectl get cm -n sam-solace-lab dashboard-sam-retail-ops >/dev/null 2>&1 \
    && echo "   WOULD delete ConfigMap dashboard-sam-retail-ops" \
    || echo "   dashboard: not present"
else
  kubectl delete cm -n sam-solace-lab dashboard-sam-retail-ops \
    --ignore-not-found | sed 's/^/   /'
fi

if [ "$PURGE" -eq 1 ]; then
  echo "== MongoDB (container + volume)"
  if [ "$DRY" -eq 1 ]; then
    echo "   WOULD run: docker compose -f mongodb/docker-compose.yaml down -v"
  else
    docker compose -f "$SCRIPT_DIR/mongodb/docker-compose.yaml" down -v \
      | sed 's/^/   /' || true
  fi
fi

echo ""
[ "$DRY" -eq 1 ] && echo "Dry run - nothing was changed." \
  || echo "Demo removed. The retail core, models, RBAC and platform stay."
