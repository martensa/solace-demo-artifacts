#!/bin/bash
set -euo pipefail

# =============================================================
# install.sh -- layer the Event-Driven Manufacturing Ops demo
# onto a running agent-mesh-deployment (idempotent; safe to
# re-run).
# =============================================================
# Prerequisites (from agent-mesh-deployment):
#   ./scripts/setup-keycloak-client.sh + setup-keycloak-users.sh
#   ./scripts/load-images.sh && ./scripts/start.sh
#   sam auth login solace-lab --url https://sam.solace.lab
#   ./scripts/rbac/apply-rbac.sh
#
# What this installs on top:
#   1. Host data stores: postgres+pgadmin (mfg_* DBs seeded from
#      postgres/), MongoDB mfg-plant-mongo (port 27017) incl.
#      first-run seed
#   2. Manufacturing core package (core/: CRM/OMS/PDM/SCM
#      connectors, schema skills, query experts)
#   3. The 5 additional model aliases (idempotent re-apply; on a
#      fresh install start.sh skipped them for lack of a login)
#   4. Demo overlay (mesh/): clerk, quality incident reporter,
#      supply chain watcher, the two workflows and the
#      plant-events entrypoint -- the Shop Floor Analyst is
#      created first from fallback/ (workflow xref needs it),
#      then removed again unless --with-analyst (live Builder
#      demo!)
#   5. Eval package (dataset + quality gate + model benchmark)
#   6. Demo dashboard (Grafana ConfigMap)
#
#   ./install.sh                 # clean state for the live demo
#   ./install.sh --with-analyst  # keep Shop Floor Analyst + connectors
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AMD="$REPO_DIR/agent-mesh-deployment"
SAM_URL="https://sam.solace.lab"

WITH_ANALYST=0
case "${1:-}" in
  --with-analyst) WITH_ANALYST=1 ;;
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
if [ "$(docker inspect -f '{{.State.Running}}' retail-pos-mongo 2>/dev/null)" = "true" ]; then
  docker stop retail-pos-mongo >/dev/null \
    && echo "   retail-pos-mongo: stopped (port 27017 for mfg-plant-mongo)"
fi
docker compose -f "$SCRIPT_DIR/mongodb/docker-compose.yaml" up -d 2>&1 \
  | grep -viE "Running|Started" || true
echo "   mfg-plant-mongo: up (seed runs only on first volume init)"

echo "== 2/6 Manufacturing core (core/)"
(cd "$SCRIPT_DIR/core" && "$SAM_CLI" config apply 2>&1 \
  | grep -viE "^time=" | grep -E "\+|~|\*|error|fail" | head -20) || true

echo "== 3/6 Additional model aliases"
"$AMD/scripts/models/apply-models.sh" 2>&1 | tail -8

echo "== 4/6 Demo overlay (mesh/)"
# The workflows xref-validate against the Shop Floor Analyst ->
# ensure it exists BEFORE the mesh apply (create from fallback if
# missing).
SFA_ID=$(api GET /api/v1/platform/agents | python3 -c "
import json,sys
for a in json.load(sys.stdin).get('data',[]):
    if a['name']=='Shop Floor Analyst': print(a['id'])")
if [ -z "$SFA_ID" ]; then
  echo "   Shop Floor Analyst missing -> creating from fallback/"
  (cd "$SCRIPT_DIR/fallback" && "$SAM_CLI" config apply 2>&1 \
    | grep -viE "^time=" | grep -E "\+|~|\*|error" | head -8)
fi
(cd "$SCRIPT_DIR/mesh" && "$SAM_CLI" config apply 2>&1 \
  | grep -viE "^time=" | grep -E "\+|~|\*|error|fail" | head -14)

if [ "$WITH_ANALYST" -eq 0 ]; then
  echo "   removing Shop Floor Analyst + connectors (live Builder demo)"
  SFA_ID=$(api GET /api/v1/platform/agents | python3 -c "
import json,sys
for a in json.load(sys.stdin).get('data',[]):
    if a['name']=='Shop Floor Analyst': print(a['id'])")
  [ -n "$SFA_ID" ] && api DELETE "/api/v1/platform/agents/$SFA_ID" >/dev/null \
    && echo "   Shop Floor Analyst deleted (HTTP $API_CODE)"
  for con in mfg-telemetry mfg-consumption; do
    CON_ID=$(api GET /api/v1/platform/connectors | python3 -c "
import json,sys
for c in json.load(sys.stdin).get('data',[]):
    if c['name']=='$con': print(c['id'])")
    [ -n "$CON_ID" ] && api DELETE "/api/v1/platform/connectors/$CON_ID" >/dev/null \
      && echo "   $con connector deleted (HTTP $API_CODE)"
  done
else
  echo "   keeping Shop Floor Analyst (--with-analyst)"
fi

echo "== 5/6 Eval package"
(cd "$SCRIPT_DIR/eval" && "$SAM_CLI" config apply 2>&1 \
  | grep -viE "^time=" | grep -E "\+|~|=|error|fail" | head -8)
echo "   NOTE: experiments have no runs yet on a fresh platform --"
echo "   pre-run before the demo (~15 min):"
echo "     sam eval run mfg-ops-quality --url $SAM_URL --threshold 0.8"
echo "     sam eval run mfg-ops-model-benchmark --url $SAM_URL"

echo "== 6/6 Demo dashboard"
kubectl apply -f "$SCRIPT_DIR/observability/dashboard-sam-mfg-ops.yaml"

echo ""
echo "Done. Run the pre-flight checklist in talk-track.md before"
echo "going live (models probe, kyverno/monitoring health, cockpit LED)."
