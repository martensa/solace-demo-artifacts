#!/usr/bin/env bash
#
# create.sh -- Ensure connectors exist, then create (NOT deploy) one or more
# Solace Agent Mesh agents via the Platform REST API.
#
# Fully portable -- works in ANY SAM environment without manual ID edits:
#   * the model id is resolved dynamically from its alias (default: general)
#   * for each agent, its connector is ensured by name: reused if it already
#     exists, otherwise created from the connector JSON (DB user/password are
#     injected centrally below); the resulting id is then injected into the agent
#   * each agent is created with CONFIG only -- deploying is a separate step
#     (the ready-to-run deploy commands are printed at the end)
#
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  ./create.sh                          # auto-detect token from local Chrome
  ./create.sh -t '<sam_access_token>'  # pass token explicitly
  SAM_TOKEN='<token>' ./create.sh      # token via environment
  ./create.sh --dry-run                # resolve + report, create nothing

Token resolution order:  -t/--token  >  $SAM_TOKEN  >  Chrome localStorage.

Optional env:
  SAM_BASE      (default https://sam.solace.lab)
  MODEL_ALIAS   (default general)
  DB_USERNAME   (default postgres)  -- used only when a connector is CREATED
  DB_PASSWORD   (default postgres)  -- used only when a connector is CREATED
USAGE
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAM_BASE="${SAM_BASE:-https://sam.solace.lab}"
MODEL_ALIAS="${MODEL_ALIAS:-general}"
DB_USERNAME="${DB_USERNAME:-postgres}"
DB_PASSWORD="${DB_PASSWORD:-postgres}"
TOKEN="${SAM_TOKEN:-}"
DRY_RUN=0

# --- Agent <-> connector pairs (files are relative to this script's dir) ------
# Add another agent by appending one line plus its two JSON files. No other edit.
PAIRS=(
  "agent-retail_crm_query_expert.json|connector-retail_crm_db.json"
  "agent-retail_oms_query_expert.json|connector-retail_oms_db.json"
  "agent-retail_pdm_query_expert.json|connector-retail_pdm_db.json"
)

while [ $# -gt 0 ]; do
  case "$1" in
    -t|--token) TOKEN="${2:-}"; shift 2 ;;
    --dry-run)  DRY_RUN=1; shift ;;
    -h|--help)  usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

command -v curl >/dev/null 2>&1 || { echo "ERROR: curl not found." >&2; exit 1; }
command -v jq   >/dev/null 2>&1 || { echo "ERROR: jq not found (brew install jq)." >&2; exit 1; }

# Validate every referenced file up front.
for pair in "${PAIRS[@]}"; do
  for f in "$SCRIPT_DIR/${pair%%|*}" "$SCRIPT_DIR/${pair##*|}"; do
    [ -f "$f" ] || { echo "ERROR: file not found: $f" >&2; exit 1; }
    jq -e . "$f" >/dev/null 2>&1 || { echo "ERROR: $f is not valid JSON." >&2; exit 1; }
  done
done

# --- best-effort: read sam_access_token from the local Chrome localStorage ---
_auto_token() {
  set +e
  local now best best_exp f jwt payload iss exp
  now=$(date +%s); best=""; best_exp=0
  for f in "$HOME/Library/Application Support/Google/Chrome/"*"/Local Storage/leveldb/"*.log \
           "$HOME/Library/Application Support/Google/Chrome/"*"/Local Storage/leveldb/"*.ldb; do
    [ -f "$f" ] || continue
    while IFS= read -r jwt; do
      payload=$(printf '%s' "$jwt" | cut -d. -f2 | tr '_-' '/+')
      case $(( ${#payload} % 4 )) in 2) payload="$payload==";; 3) payload="$payload=";; esac
      payload=$(printf '%s' "$payload" | base64 -D 2>/dev/null || printf '%s' "$payload" | base64 -d 2>/dev/null)
      [ -n "$payload" ] || continue
      iss=$(printf '%s' "$payload" | jq -r '.iss // empty' 2>/dev/null)
      [ "$iss" = "agent-mesh-solace-agent-mesh-gateway" ] || continue
      exp=$(printf '%s' "$payload" | jq -r '.exp // 0' 2>/dev/null)
      [[ "$exp" =~ ^[0-9]+$ ]] || continue
      if [ "$exp" -gt "$best_exp" ]; then best_exp="$exp"; best="$jwt"; fi
    done < <(strings "$f" 2>/dev/null | grep -oE 'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+' | sort -u)
  done
  [ -n "$best" ] && [ "$best_exp" -gt "$now" ] && printf '%s' "$best"
}

if [ -z "$TOKEN" ]; then
  echo "No token via -t/SAM_TOKEN -- trying local Chrome localStorage ..." >&2
  TOKEN="$(_auto_token || true)"
  [ -n "$TOKEN" ] && echo "Auto-detected sam_access_token from Chrome." >&2
fi
if [ -z "$TOKEN" ]; then
  echo "ERROR: could not obtain a token automatically." >&2
  echo "Pass it explicitly:   ./create.sh -t '<sam_access_token>'" >&2
  echo "Get it from the DevTools console on a logged-in $SAM_BASE tab:" >&2
  echo "    copy(localStorage.getItem('sam_access_token'))" >&2
  exit 1
fi

AUTH=(-H "Authorization: Bearer $TOKEN")
api() { curl -sSk "${AUTH[@]}" "$@"; }

# --- CSRF token + model id (resolved once) ----------------------------------
CSRF=$(api "$SAM_BASE/api/v1/csrf-token" | jq -r '.csrf_token // empty')
[ -n "$CSRF" ] || { echo "ERROR: failed to obtain CSRF token (token expired/invalid?)." >&2; exit 1; }

MODEL_ID=$(api "$SAM_BASE/api/v1/platform/models" \
  | jq -r --arg a "$MODEL_ALIAS" 'first(.data[] | select(.alias==$a) | .id) // empty')
[ -n "$MODEL_ID" ] || { echo "ERROR: model alias '$MODEL_ALIAS' not found." >&2; exit 1; }
echo "Model '$MODEL_ALIAS' -> $MODEL_ID" >&2

# --- ensure a connector exists (by name) -> echoes its id -------------------
ensure_connector() {
  local cfile="$1" cname cid resp cbody
  cname=$(jq -r '.name' "$cfile")
  cid=$(api "$SAM_BASE/api/v1/platform/connectors" \
    | jq -r --arg n "$cname" 'first(.data[] | select(.name==$n) | .id) // empty')
  if [ -n "$cid" ]; then
    echo "  connector '$cname' exists -> $cid" >&2
  elif [ "$DRY_RUN" -eq 1 ]; then
    echo "  connector '$cname' MISSING -> would create from $(basename "$cfile")" >&2
    cid="<<created-on-real-run>>"
  else
    echo "  connector '$cname' missing -- creating (user=$DB_USERNAME) ..." >&2
    cbody=$(jq --arg u "$DB_USERNAME" --arg p "$DB_PASSWORD" \
      '.values.username = $u | .values.password = $p' "$cfile")
    resp=$(curl -sSk "${AUTH[@]}" -H "X-CSRF-TOKEN: $CSRF" -H 'Content-Type: application/json' \
      -X POST "$SAM_BASE/api/v1/platform/connectors" --data-binary "$cbody")
    cid=$(printf '%s' "$resp" | jq -r '.data.id // empty')
    if [ -z "$cid" ]; then
      echo "  ERROR creating connector '$cname':" >&2
      printf '%s\n' "$resp" | jq . >&2 2>/dev/null || printf '%s\n' "$resp" >&2
      return 1
    fi
    echo "  connector created -> $cid" >&2
  fi
  printf '%s' "$cid"
}

# --- process every pair ------------------------------------------------------
CREATED=()
for pair in "${PAIRS[@]}"; do
  afile="$SCRIPT_DIR/${pair%%|*}"
  cfile="$SCRIPT_DIR/${pair##*|}"
  aname=$(jq -r '.name' "$afile")
  echo "=== $aname ===" >&2

  cid=$(ensure_connector "$cfile") || exit 1

  payload=$(jq --arg m "$MODEL_ID" --arg c "$cid" \
    '.modelProvider = [$m] | .connectors = [$c]' "$afile")

  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  would create agent '$aname' (model=$MODEL_ID connector=$cid)" >&2
    continue
  fi

  resp=$(curl -sSk "${AUTH[@]}" -H "X-CSRF-TOKEN: $CSRF" -H 'Content-Type: application/json' \
    -X POST "$SAM_BASE/api/v1/platform/agents" --data-binary "$payload")
  aid=$(printf '%s' "$resp" | jq -r '.data.id // empty')
  if [ -z "$aid" ]; then
    echo "  ERROR creating agent '$aname':" >&2
    printf '%s\n' "$resp" | jq . >&2 2>/dev/null || printf '%s\n' "$resp" >&2
    exit 1
  fi
  echo "  agent created (not deployed) -> $aid" >&2
  CREATED+=("$aname|$aid")
done

if [ "$DRY_RUN" -eq 1 ]; then
  echo "" >&2; echo "DRY RUN complete -- nothing was created." >&2
  exit 0
fi

echo ""
echo "Created ${#CREATED[@]} agent(s) (NOT deployed):"
for e in "${CREATED[@]}"; do printf '  %-28s %s\n' "${e%%|*}" "${e##*|}"; done
echo ""
echo "To deploy all of them now, paste:"
echo "  CSRF=\$(curl -sSk -H \"Authorization: Bearer \$SAM_TOKEN\" $SAM_BASE/api/v1/csrf-token | jq -r .csrf_token)"
for e in "${CREATED[@]}"; do
  echo "  curl -sSk -H \"Authorization: Bearer \$SAM_TOKEN\" -H \"X-CSRF-TOKEN: \$CSRF\" -H 'Content-Type: application/json' -X POST $SAM_BASE/api/v1/platform/agentDeployments -d '{\"agentId\":\"${e##*|}\",\"action\":\"deploy\"}'"
done
