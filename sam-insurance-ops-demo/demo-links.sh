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
# Profile-aware: the block of the installed profile is printed
# (claims-triage entrypoint => triage, claims-events => extended;
# neither => both, with "(not on platform)" markers).
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

# Profile detection from the entrypoints on the platform.
GW_NAMES=$(fetch /api/v1/platform/entrypoints | python3 -c "
import json,sys
try:
    for x in json.load(sys.stdin).get('data',[]): print(x.get('name',''))
except Exception: pass")
SHOW_TRIAGE=1; SHOW_EXT=1
if grep -qxF claims-triage <<<"$GW_NAMES"; then SHOW_EXT=0
elif grep -qxF claims-events <<<"$GW_NAMES"; then SHOW_TRIAGE=0
fi

# =============================================================
# TRIAGE profile ("Claim Triage in 30 Seconds")
# =============================================================
if [ "$SHOW_TRIAGE" -eq 1 ]; then
echo "== Triage profile: control-layer pages (window A, sam_admin)"
printf "   %-32s %s\n" "Agent Management (window A)" "$SAM_URL/#/agent-management"
printf "   %-32s %s\n" "Models"                      "$SAM_URL/#/models"
printf "   %-32s %s\n" "Connectors"                  "$SAM_URL/#/connectors"
printf "   %-32s %s\n" "Workflows"                   "$SAM_URL/#/agents/workflows"
printf "   %-32s %s\n" "Entrypoints"                 "$SAM_URL/#/entrypoints"
printf "   %-32s %s\n" "Activities (window B)"       "$SAM_URL/#/activities"
printf "   %-32s %s\n" "Evaluations (window E)"      "$SAM_URL/#/evaluations"
printf "   %-32s %s\n" "Evaluations lab"             "$SAM_URL/#/evaluations/lab?tab=experiments"

echo "== Triage workflow (display-name link is STABLE across installs)"
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

echo "== Triage agents"
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

echo "== Triage entrypoint"
ids_by_name /api/v1/platform/entrypoints claims-triage \
  | while IFS=$'\t' read -r name id; do
      [ "$id" = "NOT-FOUND" ] \
        && printf "   %-32s (not on platform)\n" "$name" \
        || printf "   %-32s %s/#/entrypoints/%s\n" "$name" "$SAM_URL" "$id"
    done

echo "== Grafana (window D) + Tempo"
printf "   %-32s %s\n" "SAM Claims Governance" \
  "$GRAFANA_URL/d/sam-claims-governance"
printf "   %-32s %s\n" "Tempo Explore" "$GRAFANA_URL/explore"
printf "   %-32s %s\n" "  TraceQL for the claim" \
  '{ name =~ ".*a2a/v1/agent/request.*" }'
fi

# =============================================================
# EXTENDED profile (the event-driven acts)
# =============================================================
if [ "$SHOW_EXT" -eq 1 ]; then
echo "== Extended workflows (display-name links are STABLE across installs)"
printf "   %-32s %s\n" "Stalled Cohort Report" \
  "$SAM_URL/#/agents/workflows/Stalled%20Cohort%20Report"
printf "   %-32s %s\n" "Storm Readiness" \
  "$SAM_URL/#/agents/workflows/Storm%20Readiness"
printf "   %-32s %s\n" "Cross-Channel Fraud Report" \
  "$SAM_URL/#/agents/workflows/Cross-Channel%20Fraud%20Report"
ids_by_name /api/v1/platform/workflows \
    stalled-cohort-report storm-readiness cross-channel-fraud-report \
  | while IFS=$'\t' read -r name id; do
      if [ "$id" = "NOT-FOUND" ]; then
        printf "   %-32s (not on platform)\n" "$name"
      else
        printf "   %-32s %s/#/agents/workflows/workflow_%s\n" \
          "$name (by id)" "$SAM_URL" "${id//-/_}"
      fi
    done

echo "== Extended agents"
ids_by_name /api/v1/platform/agents \
    "Orchestrator" \
    "Acme Insurance Query Expert" "Acme Claims Knowledge Expert" \
    "Fast Lane Clerk" \
    "Claims Incident Reporter" "Storm Readiness Planner" \
    "Fraud Case Reporter" \
    "Storm Intake Analyst" \
  | while IFS=$'\t' read -r name id; do
      if [ "$id" = "NOT-FOUND" ]; then
        if [ "$name" = "Storm Intake Analyst" ]; then
          printf "   %-32s (absent = live Builder beat ready)\n" "$name"
        else
          printf "   %-32s (not on platform -- ./install.sh --extended)\n" "$name"
        fi
      else
        printf "   %-32s %s/#/agent-management?id=%s\n" "$name" "$SAM_URL" "$id"
      fi
    done

echo "== Extended connectors"
ids_by_name /api/v1/platform/connectors \
    "Acme Insurance DB" "Acme Claims Knowledge" \
    "fnol-intake" "weather-cells" "scanner-results" \
  | while IFS=$'\t' read -r name id; do
      if [ "$id" = "NOT-FOUND" ]; then
        printf "   %-32s (not on platform)\n" "$name"
      else
        printf "   %-32s %s/#/connectors/%s\n" "$name" "$SAM_URL" "$id"
      fi
    done

echo "== Extended entrypoint"
ids_by_name /api/v1/platform/entrypoints claims-events \
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
printf "   %-32s %s\n" "Grafana (window D)"          "$GRAFANA_URL/d/sam-insurance-ops"
fi
