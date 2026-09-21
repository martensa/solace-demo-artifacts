#!/bin/bash
set -euo pipefail

# =============================================================
# demo-links.sh -- print direct SAM UI links for the demo
# (talk-track click paths, window setup, rehearsal).
#
# The UI is hash-routed. Link patterns (verified against the app
# bundle and the live deployment, 2026-08-10; the workflow route
# re-checked on 2.348.22, 2026-09-21):
#   workflow    #/agents/workflows/<display name, URL-encoded>
#               or #/agents/workflows/workflow_<platform-id, - -> _>
#               (the route resolves the card name or display name;
#               a config-name link shows "Workflow not found")
#   agent       #/agent-management?id=<platform-id>
#   connector   #/connectors/<platform-id>
#   entrypoint  #/entrypoints/<platform-id>
# IDs change on every re-install -> always regenerate. Requires a
# valid sam CLI login:
#   sam auth login solace-lab --url https://sam.solace.lab
#
# A leftover claims-events entrypoint of the removed extended
# profile (installs from an older checkout) is reported as a
# WARNING: next to claims-triage it answers the same FNOL events
# (./preflight.sh or ./install.sh deletes it); without
# claims-triage the lab still runs the old profile (re-install:
# ./uninstall.sh && ./install.sh).
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AMD="$(cd "$SCRIPT_DIR/../agent-mesh-deployment" && pwd)"
SAM_URL="https://sam.solace.lab"
# Grafana of the lab (kube-prometheus-stack, ingress monitoring.solace.lab)
GRAFANA_URL="https://monitoring.solace.lab"

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
  local code p="$1"
  # 2.348.22 pages every list endpoint (default 20 per page, newest
  # first): read the maximum page of 100 (the demos stay far below).
  case "$p" in *\?*) ;; *) p="$p?pageSize=100" ;; esac
  code=$(curl -sk -m 20 "$SAM_URL$p" \
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

# Legacy check: the entrypoint of the removed extended profile.
GW_NAMES=$(fetch /api/v1/platform/entrypoints | python3 -c "
import json,sys
try:
    for x in json.load(sys.stdin).get('data',[]): print(x.get('name',''))
except Exception: pass")
if grep -qxF claims-events <<<"$GW_NAMES"; then
  echo "WARNING: legacy entrypoint 'claims-events' (removed extended profile)"
  if grep -qxF claims-triage <<<"$GW_NAMES"; then
    echo "  answers the same FNOL events -- run ./preflight.sh (step 4) or"
    echo "  ./install.sh before the show; both delete it."
  else
    echo "  and no claims-triage: this lab still runs the old profile --"
    echo "  re-install the claim triage demo: ./uninstall.sh && ./install.sh"
  fi
  echo ""
fi

echo "== Control-layer pages (window A, sam_admin)"
printf "   %-32s %s\n" "Agent Management (window A)" "$SAM_URL/#/agent-management"
printf "   %-32s %s\n" "Models"                      "$SAM_URL/#/models"
printf "   %-32s %s\n" "Connectors"                  "$SAM_URL/#/connectors"
printf "   %-32s %s\n" "Workflows"                   "$SAM_URL/#/agents/workflows"
printf "   %-32s %s\n" "Entrypoints"                 "$SAM_URL/#/entrypoints"
printf "   %-32s %s\n" "Activities (window B)"       "$SAM_URL/#/activities"
printf "   %-32s %s\n" "Evaluations (window A, tab 6)" "$SAM_URL/#/evaluations"
printf "   %-32s %s\n" "Evaluations lab"             "$SAM_URL/#/evaluations/lab?tab=experiments"

echo "== Workflow (display-name link is STABLE across installs)"
printf "   %-32s %s\n" "Claim Triage" \
  "$SAM_URL/#/agents/workflows/Claim%20Triage"
ids_by_name /api/v1/platform/workflows claim-triage \
  | while IFS=$'\t' read -r name id; do
      if [ "$id" = "NOT-FOUND" ]; then
        printf "   %-32s (not on platform -- ./install.sh)\n" "$name"
      else
        printf "   %-32s %s/#/agents/workflows/workflow_%s\n" \
          "$name (by id)" "$SAM_URL" "${id//-/_}"
      fi
    done

echo "== Agents"
# In workflow-node order: policy, intake, rules, decision. The intake
# node runs on the Claims Intake Liaison, whose
# interAgentCommunication allow list names the external Claims Intake
# Analyst as its only peer -- open it to show that one-line reach.
ids_by_name /api/v1/platform/agents \
    "Acme Insurance Query Expert" "Claims Intake Liaison" \
    "Acme Claims Knowledge Expert" "Claims Triage Decision" \
  | while IFS=$'\t' read -r name id; do
      if [ "$id" = "NOT-FOUND" ]; then
        printf "   %-32s (not on platform -- ./install.sh)\n" "$name"
      else
        printf "   %-32s %s/#/agent-management?id=%s\n" "$name" "$SAM_URL" "$id"
      fi
    done
printf "   %-32s %s\n" "Claims Intake Analyst (external)" \
  "discovered over the broker: Agent Management -> type 'discovered'"

echo "== Entrypoint"
ids_by_name /api/v1/platform/entrypoints claims-triage \
  | while IFS=$'\t' read -r name id; do
      [ "$id" = "NOT-FOUND" ] \
        && printf "   %-32s (not on platform -- ./install.sh)\n" "$name" \
        || printf "   %-32s %s/#/entrypoints/%s\n" "$name" "$SAM_URL" "$id"
    done

echo "== Grafana (window A, tab 5) + Tempo"
printf "   %-32s %s\n" "SAM Claims Governance" \
  "$GRAFANA_URL/d/sam-claims-governance"
printf "   %-32s %s\n" "Tempo Explore" "$GRAFANA_URL/explore"
printf "   %-32s %s\n" "  TraceQL for the claim" \
  '{ name =~ ".*a2a/v1/agent/request.*" }'
