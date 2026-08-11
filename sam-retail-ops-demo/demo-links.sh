#!/bin/bash
set -euo pipefail

# =============================================================
# demo-links.sh -- print direct SAM UI links for the demo
# (talk-track click paths, window setup, rehearsal).
#
# The UI is hash-routed. Link patterns (verified against the app
# bundle and the live deployment, 2026-08-11):
#   workflow    #/agents/workflows/<display name, URL-encoded>
#               (STABLE across re-installs) and
#               #/agents/workflows/workflow_<platform-id, - -> _>
#   agent       #/agent-management?id=<platform-id>
#   connector   #/connectors/<platform-id>
#   entrypoint  #/entrypoints/<platform-id>
# IDs change on every re-install -> always regenerate. Requires a
# valid sam CLI login:
#   sam auth login solace-lab --url https://sam.solace.lab
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AMD="$(cd "$SCRIPT_DIR/../agent-mesh-deployment" && pwd)"
SAM_URL="https://sam.solace.lab"

# shellcheck source=../agent-mesh-deployment/scripts/lib/common.sh
. "$AMD/scripts/lib/common.sh"
load_env "$AMD"
resolve_sam_cli

# The cached access token is short-lived, but any real CLI call
# refreshes the cache via the stored refresh token. Run a cheap
# read-only plan first so the raw curl calls below get a fresh
# token (falls back to the login hint on real auth failure).
(cd "$SCRIPT_DIR/eval" && "$SAM_CLI" config plan >/dev/null 2>&1) || true
sam_auth_token

fetch() {  # fetch PATH -> body (exits with hint on auth failure)
  local code
  code=$(curl -sk -m 20 "$SAM_URL$1" \
    -H "Authorization: Bearer $SAM_AUTH_TOKEN" \
    -o /tmp/demo-links-body.json -w "%{http_code}")
  if [ "$code" != "200" ]; then
    echo "ERROR: $1 returned HTTP $code (token expired?)." >&2
    echo "  sam auth login solace-lab --url $SAM_URL" >&2
    exit 1
  fi
  cat /tmp/demo-links-body.json
}

ids_by_name() {  # ids_by_name PATH NAME... -> "name<TAB>id" lines
  local path="$1"; shift
  fetch "$path" | python3 -c "
import json,sys
want = sys.argv[1:]
try: data = json.load(sys.stdin).get('data',[])
except Exception: data = []
by = {x['name']: x['id'] for x in data}
for n in want:
    print(n + '\t' + by.get(n, 'NOT-FOUND'))" "$@"
}

# Fail fast (outside any pipeline) if the token is invalid.
fetch /api/v1/platform/agents >/dev/null

echo "== Workflows (display-name links are STABLE across installs)"
printf "   %-32s %s\n" "Order Incident Report" \
  "$SAM_URL/#/agents/workflows/Order%20Incident%20Report"
printf "   %-32s %s\n" "Retail 360 Report" \
  "$SAM_URL/#/agents/workflows/Retail%20360%20Report"
ids_by_name /api/v1/platform/workflows \
    order-incident-report retail-360-report \
  | while IFS=$'\t' read -r name id; do
      if [ "$id" = "NOT-FOUND" ]; then
        printf "   %-32s (not on platform)\n" "$name"
      else
        printf "   %-32s %s/#/agents/workflows/workflow_%s\n" \
          "$name (by id)" "$SAM_URL" "${id//-/_}"
      fi
    done

echo "== Agents"
ids_by_name /api/v1/platform/agents \
    "Orchestrator" \
    "Retail CRM Query Expert" "Retail OMS Query Expert" \
    "Retail PDM Query Expert" "Retail 360 Reporter" \
    "Order Confirmation Clerk" "Order Incident Reporter" \
    "Retail POS Analyst" \
  | while IFS=$'\t' read -r name id; do
      if [ "$id" = "NOT-FOUND" ]; then
        if [ "$name" = "Retail POS Analyst" ]; then
          printf "   %-32s (absent = live Builder beat ready)\n" "$name"
        else
          printf "   %-32s (not on platform -- ./install.sh)\n" "$name"
        fi
      else
        printf "   %-32s %s/#/agent-management?id=%s\n" "$name" "$SAM_URL" "$id"
      fi
    done

echo "== Connectors"
ids_by_name /api/v1/platform/connectors \
    "Retail CRM DB" "Retail OMS DB" "Retail PDM DB" \
    "retail-poslog" \
  | while IFS=$'\t' read -r name id; do
      if [ "$id" = "NOT-FOUND" ]; then
        printf "   %-32s (not on platform)\n" "$name"
      else
        printf "   %-32s %s/#/connectors/%s\n" "$name" "$SAM_URL" "$id"
      fi
    done

echo "== Entrypoints"
ids_by_name /api/v1/platform/gateways shop-events developer-mcp \
  | while IFS=$'\t' read -r name id; do
      [ "$id" = "NOT-FOUND" ] \
        && printf "   %-32s (not on platform)\n" "$name" \
        || printf "   %-32s %s/#/entrypoints/%s\n" "$name" "$SAM_URL" "$id"
    done

echo "== Fixed pages (window setup)"
printf "   %-32s %s\n" "Agent Management (window A)" "$SAM_URL/#/agent-management"
printf "   %-32s %s\n" "Entrypoints"                 "$SAM_URL/#/entrypoints"
printf "   %-32s %s\n" "Activities (window B)"       "$SAM_URL/#/activities"
printf "   %-32s %s\n" "Evaluations lab"             "$SAM_URL/#/evaluations/lab?tab=experiments"
