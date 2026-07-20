#!/bin/bash
set -euo pipefail

# =============================================================
# set-max-tokens.sh (SAM v2) -- set modelParams.max_tokens on a
# model configuration via the sam CLI, then restart the
# Agent-Workflow Executor so agents re-read the model config.
# =============================================================
# Default value is 16384. Pass a different value as the
# positional argument.
#
# Auth: uses the sam CLI login cache from
#   sam auth login solace-lab --url https://sam.solace.lab
# (the token is exported as SAM_AUTH_TOKEN because the EA
# `sam api` does not attach the cached OAuth token itself).
# =============================================================

usage() {
  cat <<'USAGE'
Usage:
  ./set-max-tokens.sh [VALUE]              # set max_tokens (default 16384)
  ./set-max-tokens.sh --model-alias planning VALUE
  ./set-max-tokens.sh --dry-run [VALUE]    # show current + intended, no change
  ./set-max-tokens.sh --no-restart VALUE   # patch only, do not restart agents

Optional env:
  MODEL_ALIAS     (default general)
  SAM_NAMESPACE   (default sam-solace-lab)
USAGE
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

MODEL_ALIAS="${MODEL_ALIAS:-general}"
SAM_NAMESPACE="${SAM_NAMESPACE:-sam-solace-lab}"
AUTH_CACHE="$HOME/Library/Application Support/sam/auth/solace-lab.json"
DRY_RUN=0
RESTART=1
MAX_TOKENS=16384

while [ $# -gt 0 ]; do
  case "$1" in
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

command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found." >&2; exit 1; }

# --- Resolve the sam CLI (same order as scripts/rbac) --------------
if [ -f "$PROJECT_DIR/.env" ]; then
  # shellcheck source=/dev/null
  . "$PROJECT_DIR/.env"
fi
SAM_CLI=""
if [ -n "${SAM_CLI_PATH:-}" ] && [ -x "$SAM_CLI_PATH" ]; then
  SAM_CLI="$SAM_CLI_PATH"
elif command -v sam >/dev/null 2>&1; then
  SAM_CLI="$(command -v sam)"
fi
if [ -z "$SAM_CLI" ]; then
  echo "ERROR: sam CLI not found. Set SAM_CLI_PATH in .env or put" >&2
  echo "'sam' on the PATH (see scripts/rbac/README.md)." >&2
  exit 1
fi

# --- Token from the login cache ------------------------------------
if [ ! -f "$AUTH_CACHE" ]; then
  echo "ERROR: no sam CLI login cache. Log in first:" >&2
  echo "  $SAM_CLI auth login solace-lab --url https://sam.solace.lab" >&2
  exit 1
fi
SAM_AUTH_TOKEN=$(python3 -c \
  "import json;print(json.load(open('$AUTH_CACHE'))['sam_access_token'])")
export SAM_AUTH_TOKEN

# --- Resolve model + current params --------------------------------
# Note: the EA sam CLI prints its log lines on stdout; keep only the
# JSON payload line(s) before parsing.
MODEL_JSON=$("$SAM_CLI" api /api/v1/platform/models 2>/dev/null \
  | python3 -c "
import sys, json
raw = ''.join(l for l in sys.stdin if l.lstrip().startswith(('{','[')))
d = json.loads(raw)
rows = d.get('data') if isinstance(d, dict) else d
m = next((r for r in rows or [] if (r.get('alias') or r.get('name')) == '$MODEL_ALIAS'), None)
print(json.dumps(m) if m else '')")
[ -n "$MODEL_JSON" ] || {
  echo "ERROR: model alias '$MODEL_ALIAS' not found (token expired?" >&2
  echo "Re-run: $SAM_CLI auth login solace-lab --url https://sam.solace.lab)" >&2
  exit 1; }

MODEL_ID=$(printf '%s' "$MODEL_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
CURRENT=$(printf '%s' "$MODEL_JSON" | python3 -c "import sys,json;print(json.dumps(json.load(sys.stdin).get('modelParams') or {}))")
NEW_PARAMS=$(printf '%s' "$CURRENT" | python3 -c "
import sys, json
p = json.load(sys.stdin)
p['max_tokens'] = $MAX_TOKENS
print(json.dumps({'modelParams': p}))")

echo "Model '$MODEL_ALIAS' ($MODEL_ID)"
echo "  current modelParams: $CURRENT"
echo "  intended:            $(printf '%s' "$NEW_PARAMS" | python3 -c 'import sys,json;print(json.dumps(json.load(sys.stdin)["modelParams"]))')"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "DRY RUN - nothing changed."
  exit 0
fi

# --- PATCH (merge; authConfig untouched) ----------------------------
APPLIED=$(printf '%s' "$NEW_PARAMS" \
  | "$SAM_CLI" api -X PATCH "/api/v1/platform/models/$MODEL_ID" --input - 2>/dev/null \
  | python3 -c "
import sys, json
raw = ''.join(l for l in sys.stdin if l.lstrip().startswith(('{','[')))
try:
    d = json.loads(raw)
except Exception:
    print(''); raise SystemExit
d = d.get('data', d)
print((d.get('modelParams') or {}).get('max_tokens', ''))" || true)
if [ "$APPLIED" != "$MAX_TOKENS" ]; then
  echo "ERROR: PATCH did not apply max_tokens=$MAX_TOKENS (got: '${APPLIED:-no response}')." >&2
  exit 1
fi
echo "max_tokens set to $MAX_TOKENS on model '$MODEL_ALIAS'."

# --- Restart the Agent-Workflow Executor ----------------------------
# Agents (and workflows) run in the awe deployment and read the
# model configuration at startup via the model bootstrap queues.
RESTART_CMD="kubectl rollout restart deployment -n $SAM_NAMESPACE -l app.kubernetes.io/component=awe"
if [ "$RESTART" -eq 0 ]; then
  echo "Skipped restart (--no-restart). Apply it later with:"
  echo "  $RESTART_CMD"
  exit 0
fi
if ! command -v kubectl >/dev/null 2>&1 || ! kubectl get ns "$SAM_NAMESPACE" >/dev/null 2>&1; then
  echo "kubectl/namespace not reachable - restart the agents manually:"
  echo "  $RESTART_CMD"
  exit 0
fi
echo "Restarting the Agent-Workflow Executor ..."
kubectl rollout restart deployment -n "$SAM_NAMESPACE" -l app.kubernetes.io/component=awe
kubectl rollout status deployment -n "$SAM_NAMESPACE" -l app.kubernetes.io/component=awe --timeout=300s || true
echo "Done - agents re-read the model config on startup."
