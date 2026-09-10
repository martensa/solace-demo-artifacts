#!/bin/bash
set -euo pipefail

# =============================================================
# install.sh -- layer the Event-Driven Claims Operations demo
# (Acme Insurance) onto a running agent-mesh-deployment
# (idempotent; safe to re-run).
# =============================================================
# Prerequisites (from agent-mesh-deployment):
#   ./scripts/setup-keycloak-client.sh + setup-keycloak-users.sh
#   ./scripts/load-images.sh && ./scripts/start.sh
#   sam auth login solace-lab --url https://sam.solace.lab
#   ./scripts/rbac/apply-rbac.sh
#
# What this installs on top:
#   1. Host data stores: postgres+pgadmin (acme_insurance DB
#      seeded from postgres/), MongoDB acme-claims-mongo (port
#      27017) incl. first-run seed
#   2. Knowledge base: Qdrant + the Acme Claims Knowledge MCP
#      server (qdrant/, built locally, port 8765) incl. the
#      one-shot corpus seed (first run downloads the embedding
#      model -- allow up to 6 minutes)
#   3. Insurance core package (core/: Insurance DB + Claims
#      Knowledge connectors, schema/guide skills, query experts)
#   4. The 5 additional model aliases (idempotent re-apply; on a
#      fresh install start.sh skipped them for lack of a login)
#   5. Demo overlay (mesh/): Fast Lane Clerk, the three reporter/
#      planner agents, the three workflows and the claims-events
#      entrypoint -- the Storm Intake Analyst is created first
#      from fallback/ (workflow xref needs it), then removed
#      again unless --with-analyst (live Builder demo!)
#   6. Eval package (dataset + quality gate + model benchmark)
#   7. Demo dashboard (Grafana ConfigMap)
#
#   ./install.sh                 # clean state for the live demo
#   ./install.sh --with-analyst  # keep Storm Intake Analyst + connectors
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AMD="$REPO_DIR/agent-mesh-deployment"
SAM_URL="https://sam.solace.lab"
MONGO_COMPOSE="$SCRIPT_DIR/mongodb/docker-compose.yaml"
QDRANT_COMPOSE="$SCRIPT_DIR/qdrant/docker-compose.yaml"
MCP_HEALTH_URL="http://localhost:8765/health"

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
# The cached access token is short-lived; any real CLI call refreshes
# it via the stored refresh token (same trick as preflight/demo-links),
# so a stale cache does not 401 the raw curl calls below.
(cd "$SCRIPT_DIR/eval" && "$SAM_CLI" config plan >/dev/null 2>&1) || true
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
OTHER_EPS=$(api GET /api/v1/platform/gateways | python3 -c "
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

echo "== 1/7 Host data stores"
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

echo "== 2/7 Knowledge base (qdrant/: Qdrant + MCP server + seed)"
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

echo "== 3/7 Insurance core (core/)"
(cd "$SCRIPT_DIR/core" && "$SAM_CLI" config apply 2>&1 \
  | grep -viE "^time=" | grep -E "\+|~|\*|error|fail" | head -20) || true

echo "== 4/7 Additional model aliases"
"$AMD/scripts/models/apply-models.sh" 2>&1 | tail -8

echo "== 5/7 Demo overlay (mesh/)"
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
  # validation (optimization inherited from the mfg demo).
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

echo "== 6/7 Eval package"
(cd "$SCRIPT_DIR/eval" && "$SAM_CLI" config apply 2>&1 \
  | grep -viE "^time=" | grep -E "\+|~|=|error|fail" | head -8)
echo "   NOTE: experiments have no runs yet on a fresh platform --"
echo "   pre-run before the demo (~15 min): ./preflight.sh does it"
echo "   automatically (the bare 'sam eval run' needs the token"
echo "   exported -- see scripts/lib/common.sh sam_auth_token)."

echo "== 7/7 Demo dashboard"
kubectl apply -f "$SCRIPT_DIR/observability/dashboard-sam-insurance-ops.yaml"

echo ""
echo "Done. Run the pre-flight checklist in talk-track.md before"
echo "going live (models probe, kyverno/monitoring health, cockpit LED)."
