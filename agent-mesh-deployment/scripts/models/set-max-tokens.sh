#!/usr/bin/env bash
#
# set-max-tokens.sh -- Set the max output tokens (modelParams.max_tokens) on a
# Solace Agent Mesh model configuration via the Platform REST API, then restart
# the agent pods so they re-read the model config on startup.
#
# Default value is 16384. Pass a different value as the positional argument.
#
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  ./set-max-tokens.sh [VALUE]             # set max_tokens (default 16384)
  ./set-max-tokens.sh -t '<token>' VALUE  # pass the token explicitly
  SAM_TOKEN='<token>' ./set-max-tokens.sh VALUE
  ./set-max-tokens.sh --dry-run VALUE     # resolve + report, change nothing
  ./set-max-tokens.sh --no-restart VALUE  # patch only, do not restart pods
  ./set-max-tokens.sh --model-alias planning VALUE

Token resolution order:  -t/--token  >  $SAM_TOKEN  >  Chrome localStorage.

Optional env:
  SAM_BASE        (default https://sam.solace.lab)
  MODEL_ALIAS     (default general)
  SAM_NAMESPACE   (default sam-solace-lab)
USAGE
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAM_BASE="${SAM_BASE:-https://sam.solace.lab}"
MODEL_ALIAS="${MODEL_ALIAS:-general}"
SAM_NAMESPACE="${SAM_NAMESPACE:-sam-solace-lab}"
TOKEN="${SAM_TOKEN:-}"
DRY_RUN=0
RESTART=1
MAX_TOKENS=16384

while [ $# -gt 0 ]; do
  case "$1" in
    -t|--token)    TOKEN="${2:-}"; shift 2 ;;
    --model-alias) MODEL_ALIAS="${2:-}"; shift 2 ;;
    --dry-run)     DRY_RUN=1; shift ;;
    --no-restart)  RESTART=0; shift ;;
    -h|--help)     usage; exit 0 ;;
    -*)            echo "Unknown argument: $1" >&2; usage >&2; exit 1 ;;
    *)             MAX_TOKENS="$1"; shift ;;
  esac
done

[[ "$MAX_TOKENS" =~ ^[0-9]+$ ]] || {
  echo "ERROR: VALUE must be a positive integer (got '$MAX_TOKENS')." >&2; exit 1; }

command -v curl >/dev/null 2>&1 || { echo "ERROR: curl not found." >&2; exit 1; }
command -v jq   >/dev/null 2>&1 || { echo "ERROR: jq not found (brew install jq)." >&2; exit 1; }

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

# dry-run without a token: report intent only (cannot resolve the model id)
if [ "$DRY_RUN" -eq 1 ] && [ -z "$TOKEN" ]; then
  echo "DRY RUN (no token): would set max_tokens=$MAX_TOKENS on model '$MODEL_ALIAS'." >&2
  exit 0
fi
if [ -z "$TOKEN" ]; then
  echo "ERROR: could not obtain a token automatically." >&2
  echo "Pass it explicitly:   ./set-max-tokens.sh -t '<sam_access_token>' $MAX_TOKENS" >&2
  echo "Get it from the DevTools console on a logged-in $SAM_BASE tab:" >&2
  echo "    copy(localStorage.getItem('sam_access_token'))" >&2
  exit 1
fi

AUTH=(-H "Authorization: Bearer $TOKEN")
api() { curl -sSk "${AUTH[@]}" "$@"; }

# --- CSRF token --------------------------------------------------------------
CSRF=$(api "$SAM_BASE/api/v1/csrf-token" | jq -r '.csrf_token // empty')
[ -n "$CSRF" ] || { echo "ERROR: failed to obtain CSRF token (token expired/invalid?)." >&2; exit 1; }

# --- resolve the model by alias and merge max_tokens into modelParams --------
MODEL=$(api "$SAM_BASE/api/v1/platform/models" \
  | jq -c --arg a "$MODEL_ALIAS" 'first(.data[] | select(.alias==$a)) // empty')
[ -n "$MODEL" ] || { echo "ERROR: model alias '$MODEL_ALIAS' not found." >&2; exit 1; }
MODEL_ID=$(printf '%s' "$MODEL" | jq -r '.id')

# Preserve any existing modelParams; only set/replace max_tokens.
NEW_PARAMS=$(printf '%s' "$MODEL" \
  | jq -c --argjson mt "$MAX_TOKENS" '(.modelParams // {}) + {max_tokens: $mt}')

echo "Model '$MODEL_ALIAS' ($MODEL_ID): modelParams -> $NEW_PARAMS" >&2

if [ "$DRY_RUN" -eq 1 ]; then
  echo "--- DRY RUN: would PATCH /api/v1/platform/models/$MODEL_ID (nothing sent) ---" >&2
  [ "$RESTART" -eq 1 ] && \
    echo "--- would then restart agent pods in namespace $SAM_NAMESPACE ---" >&2
  exit 0
fi

# --- PATCH the model (only modelParams; authConfig untouched) ----------------
RESP=$(curl -sSk "${AUTH[@]}" -H "X-CSRF-TOKEN: $CSRF" -H 'Content-Type: application/json' \
  -X PATCH "$SAM_BASE/api/v1/platform/models/$MODEL_ID" \
  --data-binary "$(jq -nc --argjson p "$NEW_PARAMS" '{modelParams: $p}')")
APPLIED=$(printf '%s' "$RESP" | jq -r '.data.modelParams.max_tokens // empty')
if [ "$APPLIED" != "$MAX_TOKENS" ]; then
  echo "ERROR: PATCH did not apply max_tokens=$MAX_TOKENS:" >&2
  printf '%s\n' "$RESP" | jq . 2>/dev/null || printf '%s\n' "$RESP"
  exit 1
fi
echo "max_tokens set to $MAX_TOKENS on model '$MODEL_ALIAS'."

# --- restart agent pods so they re-bootstrap the model config ----------------
RESTART_CMD="kubectl rollout restart deployment -n $SAM_NAMESPACE -l app.kubernetes.io/component=agent"
if [ "$RESTART" -eq 0 ]; then
  echo "Skipped pod restart (--no-restart). The change applies only after the" >&2
  echo "agents restart:" >&2
  echo "  $RESTART_CMD" >&2
  exit 0
fi
if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl not found -- restart the agents manually so the change applies:" >&2
  echo "  $RESTART_CMD" >&2
  exit 0
fi
if ! kubectl get ns "$SAM_NAMESPACE" >/dev/null 2>&1; then
  echo "Namespace $SAM_NAMESPACE not reachable -- restart the agents manually:" >&2
  echo "  $RESTART_CMD" >&2
  exit 0
fi
echo "Restarting agent pods in namespace $SAM_NAMESPACE ..." >&2
kubectl rollout restart deployment -n "$SAM_NAMESPACE" \
  -l app.kubernetes.io/component=agent 2>&1 \
  || kubectl delete pod -n "$SAM_NAMESPACE" -l app.kubernetes.io/component=agent 2>&1 \
  || true
echo "Agent pods restarting -- they re-read the model config on startup."
