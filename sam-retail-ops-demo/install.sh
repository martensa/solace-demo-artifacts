#!/bin/bash
set -euo pipefail

# =============================================================
# install.sh -- layer the Event-Driven Retail Ops demo onto a
# running agent-mesh-deployment (idempotent; safe to re-run).
# =============================================================
# Prerequisites (from agent-mesh-deployment):
#   ./scripts/setup-keycloak-client.sh + setup-keycloak-users.sh
#   ./scripts/load-images.sh && ./scripts/start.sh
#   sam auth login solace-lab --url https://sam.solace.lab
#   ./scripts/rbac/apply-rbac.sh
#
# What this installs on top:
#   1. Host data stores: postgres+pgadmin (retail_* DBs seeded
#      from postgres/), MongoDB (POSLOG) incl. first-run seed
#   2. Retail core package (core/: CRM/OMS/PDM connectors, schema
#      skills, query experts, Retail 360 Reporter + workflow)
#   3. The 5 additional model aliases (idempotent re-apply; on a
#      fresh install start.sh skipped them for lack of a login)
#   4. Demo overlay (mesh/): clerk, incident reporter, incident
#      workflow, shop-events entrypoint -- POS analyst is created
#      first from fallback/ (workflow xref needs it), then the
#      AGENT is removed again unless --with-pos (live Builder
#      demo!); the retail-poslog connector stays pre-provisioned
#   5. Eval package (dataset + quality gate + model benchmark)
#   6. Demo dashboard (Grafana ConfigMap)
#
#   ./install.sh              # clean state for the live demo
#   ./install.sh --with-pos   # keep the POS analyst agent too
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AMD="$REPO_DIR/agent-mesh-deployment"
SAM_URL="https://sam.solace.lab"

WITH_POS=0
case "${1:-}" in
  --with-pos) WITH_POS=1 ;;
  -h|--help)  grep '^#   \./' "$0" | sed 's/^#   //'; exit 0 ;;
  "") ;;
  *) echo "Unknown argument: $1" >&2; exit 1 ;;
esac

# --- Shared helpers (sam CLI + auth token) --------------------------
# shellcheck source=../agent-mesh-deployment/scripts/lib/common.sh
. "$AMD/scripts/lib/common.sh"
load_env "$AMD"
resolve_sam_cli
sam_auth_token

api() {  # api METHOD PATH -> body on stdout, code in API_CODE
  local method="$1" path="$2"
  API_CODE=$(curl -sk -m 20 -X "$method" "$SAM_URL$path" \
    -H "Authorization: Bearer $SAM_AUTH_TOKEN" \
    -o /tmp/install-api-body.json -w "%{http_code}")
  cat /tmp/install-api-body.json 2>/dev/null || true
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
OTHER_EP=$(api GET /api/v1/platform/gateways | python3 -c "
import json,sys
for g in json.load(sys.stdin).get('data',[]):
    if g.get('name')=='plant-events': print(g['id'])")
if [ -n "$OTHER_EP" ]; then
  echo "ERROR: another demo overlay is installed (entrypoint" >&2
  echo "'plant-events' found). Only one demo runs at a time." >&2
  echo "Remove it first:  (cd ../sam-manufacturing-ops-demo && ./uninstall.sh)" >&2
  exit 1
fi

echo "== 1/6 Host data stores"
for c in postgres pgadmin; do
  if [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" = "true" ]; then
    echo "   $c: running"
  else
    docker start "$c" >/dev/null && echo "   $c: started"
  fi
done
"$SCRIPT_DIR/postgres/seed.sh" | sed 's/^/  /'
# Only one demo's mongo runs at a time (both use standard 27017).
if [ "$(docker inspect -f '{{.State.Running}}' mfg-plant-mongo 2>/dev/null)" = "true" ]; then
  docker stop mfg-plant-mongo >/dev/null \
    && echo "   mfg-plant-mongo: stopped (port 27017 for retail-pos-mongo)"
fi
docker compose -f "$SCRIPT_DIR/mongodb/docker-compose.yaml" up -d 2>&1 \
  | grep -viE "Running|Started" || true
echo "   retail-pos-mongo: up (seed runs only on first volume init)"

echo "== 2/6 Retail core (core/)"
(cd "$SCRIPT_DIR/core" && "$SAM_CLI" config apply 2>&1 \
  | grep -viE "^time=" | grep -E "\+|~|\*|error|fail" | head -20) || true

echo "== 3/6 Additional model aliases"
"$AMD/scripts/models/apply-models.sh" 2>&1 | tail -8

echo "== 4/6 Demo overlay (mesh/)"
# The workflow xref-validates against the POS analyst -> ensure it
# exists BEFORE the mesh apply (create from fallback if missing).
POS_ID=$(api GET /api/v1/platform/agents | python3 -c "
import json,sys
for a in json.load(sys.stdin).get('data',[]):
    if a['name']=='Retail POS Analyst': print(a['id'])")
if [ -z "$POS_ID" ]; then
  echo "   POS analyst missing -> creating from fallback/"
  (cd "$SCRIPT_DIR/fallback" && "$SAM_CLI" config apply 2>&1 \
    | grep -viE "^time=" | grep -E "\+|~|\*|error" | head -6)
fi
(cd "$SCRIPT_DIR/mesh" && "$SAM_CLI" config apply 2>&1 \
  | grep -viE "^time=" | grep -E "\+|~|\*|error|fail" | head -12)

if [ "$WITH_POS" -eq 0 ]; then
  # The retail-poslog connector STAYS installed (workplace
  # infrastructure, like the postgres connectors): the live
  # Builder beat only creates the AGENT binding it -- one
  # config, no connector sub-task (pre-provisioning
  # optimization backported from the manufacturing demo,
  # 2026-08-11).
  echo "   removing POS analyst (live Builder demo; connector stays)"
  POS_ID=$(api GET /api/v1/platform/agents | python3 -c "
import json,sys
for a in json.load(sys.stdin).get('data',[]):
    if a['name']=='Retail POS Analyst': print(a['id'])")
  [ -n "$POS_ID" ] && api DELETE "/api/v1/platform/agents/$POS_ID" >/dev/null \
    && echo "   POS agent deleted (HTTP $API_CODE)"
else
  echo "   keeping POS analyst (--with-pos)"
fi

echo "== 5/6 Eval package"
(cd "$SCRIPT_DIR/eval" && "$SAM_CLI" config apply 2>&1 \
  | grep -viE "^time=" | grep -E "\+|~|=|error|fail" | head -8)
echo "   NOTE: experiments have no runs yet on a fresh platform --"
echo "   pre-run before the demo (~15 min): ./preflight.sh does it"
echo "   automatically (the bare 'sam eval run' needs the token"
echo "   exported -- see scripts/lib/common.sh sam_auth_token)."

echo "== 6/6 Demo dashboard"
kubectl apply -f "$SCRIPT_DIR/observability/dashboard-sam-retail-ops.yaml"

echo ""
echo "Done. Run the pre-flight checklist in talk-track.md before"
echo "going live (models probe, kyverno/monitoring health, shop LED)."
