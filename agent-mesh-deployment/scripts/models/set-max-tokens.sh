#!/bin/bash
set -euo pipefail

# =============================================================
# set-max-tokens.sh (SAM v2) -- set modelParams.max_tokens on
# model configurations via the sam CLI, then restart the
# Agent-Workflow Executor so agents re-read the model config.
# =============================================================
# Default value is 16384. Pass a different value as the
# positional argument.
#
# Without --model-alias it tunes the three chart-seeded text
# aliases (general, planning, report_gen) in one go -- the seed
# leaves their modelParams empty. An alias already at the target
# value is left alone, and the awe restart happens once, and only
# if something changed, so re-running is cheap.
#
# Auth: uses the sam CLI login cache from
#   sam auth login solace-lab --url https://sam.solace.lab
# (the token is exported as SAM_AUTH_TOKEN because the EA
# `sam api` does not attach the cached OAuth token itself).
# =============================================================

usage() {
  cat <<'USAGE'
Usage:
  ./set-max-tokens.sh [VALUE]              # general+planning+report_gen (default 16384)
  ./set-max-tokens.sh --model-alias planning VALUE   # one alias only
  ./set-max-tokens.sh --dry-run [VALUE]    # show current + intended, no change
  ./set-max-tokens.sh --no-restart VALUE   # patch only, do not restart agents

Optional env:
  MODEL_ALIAS     (one alias instead of the seeded three)
  SAM_NAMESPACE   (default sam-solace-lab)
  SAM_ENV_FILE, SAM_HOME, SAM_URL  (target another platform, e.g.
                  AKS via aks_sam; see scripts/lib/common.sh. The
                  awe restart then runs only when KUBECONFIG names
                  one kubeconfig file whose current context is not
                  rancher-desktop and has an Ingress in
                  SAM_NAMESPACE for the SAM_URL host; otherwise it
                  is skipped with exit 2)
USAGE
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

SEEDED_ALIASES="general planning report_gen"
ALIASES="${MODEL_ALIAS:-$SEEDED_ALIASES}"
SAM_NAMESPACE="${SAM_NAMESPACE:-sam-solace-lab}"
DRY_RUN=0
RESTART=1
MAX_TOKENS=16384

while [ $# -gt 0 ]; do
  case "$1" in
    --model-alias) ALIASES="${2:-}"; shift 2 ;;
    --dry-run)     DRY_RUN=1; shift ;;
    --no-restart)  RESTART=0; shift ;;
    -h|--help)     usage; exit 0 ;;
    -*)            echo "Unknown argument: $1" >&2; usage >&2; exit 1 ;;
    *)             MAX_TOKENS="$1"; shift ;;
  esac
done

[[ "$MAX_TOKENS" =~ ^[0-9]+$ ]] || {
  echo "ERROR: VALUE must be a positive integer (got '$MAX_TOKENS')." >&2; exit 1; }
# The aliases are interpolated into inline Python below - keep them
# to a safe identifier charset.
for alias in $ALIASES; do
  [[ "$alias" =~ ^[a-z0-9_-]+$ ]] || {
    echo "ERROR: --model-alias must match [a-z0-9_-]+ (got '$alias')." >&2; exit 1; }
done
[ -n "$ALIASES" ] || { echo "ERROR: empty --model-alias." >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found." >&2; exit 1; }

# --- Shared helpers (env, sam CLI, auth token) ----------------------
# shellcheck source=../lib/common.sh
. "$PROJECT_DIR/scripts/lib/common.sh"
load_env "$PROJECT_DIR" "${SAM_ENV_FILE:-$PROJECT_DIR/.env}"
sam_target_check "$PROJECT_DIR" || exit 1
resolve_sam_cli
sam_auth_token

# --- Model list (one call for all aliases) --------------------------
# Note: the EA sam CLI prints its log lines on stdout; keep only the
# JSON payload line(s) before parsing.
# '|| true' keeps set -e from silently killing the script when the
# api call fails (e.g. expired token) - the empty-check below then
# prints the actionable re-login error instead.
# An auth failure also comes back as JSON on stdout ({"message":
# ..., "errorType": "invalid_token"}) -- only a body that carries
# a model list counts, anything else leaves MODELS_JSON empty.
MODELS_JSON=$(sam_cli_api /api/v1/platform/models 2>/dev/null \
  | python3 -c "
import sys, json
raw = ''.join(l for l in sys.stdin if l.lstrip().startswith(('{','[')))
d = json.loads(raw)
rows = d.get('data') if isinstance(d, dict) else d
if not isinstance(rows, list) or (isinstance(d, dict) and d.get('errorType')):
    raise SystemExit(1)
print(json.dumps(rows))" 2>/dev/null || true)
[ -n "$MODELS_JSON" ] || {
  echo "ERROR: could not list the platform models (token expired?" >&2
  echo "Re-run: $(sam_login_cmd))" >&2
  exit 1; }

# --- Resolve every alias first -------------------------------------
# A missing alias must stop the run BEFORE anything is patched, or a
# half-applied run would leave patched aliases without the awe
# restart (and a re-run would then skip them as "unchanged").
for MODEL_ALIAS in $ALIASES; do
  printf '%s' "$MODELS_JSON" | python3 -c "
import sys, json
sys.exit(0 if any((r.get('alias') or r.get('name')) == '$MODEL_ALIAS'
                  for r in json.load(sys.stdin)) else 1)" || {
    echo "ERROR: model alias '$MODEL_ALIAS' not found - nothing changed." >&2
    exit 1; }
done

CHANGED=0
PATCH_FAILED=0
for MODEL_ALIAS in $ALIASES; do
  MODEL_JSON=$(printf '%s' "$MODELS_JSON" | python3 -c "
import sys, json
m = next((r for r in json.load(sys.stdin)
          if (r.get('alias') or r.get('name')) == '$MODEL_ALIAS'), None)
print(json.dumps(m) if m else '')")
  [ -n "$MODEL_JSON" ] || {
    echo "ERROR: model alias '$MODEL_ALIAS' not found." >&2; exit 1; }

  MODEL_ID=$(printf '%s' "$MODEL_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
  CURRENT=$(printf '%s' "$MODEL_JSON" | python3 -c "import sys,json;print(json.dumps(json.load(sys.stdin).get('modelParams') or {}))")
  CURRENT_MAX=$(printf '%s' "$CURRENT" | python3 -c "import sys,json;print(json.load(sys.stdin).get('max_tokens',''))")
  NEW_PARAMS=$(printf '%s' "$CURRENT" | python3 -c "
import sys, json
p = json.load(sys.stdin)
p['max_tokens'] = $MAX_TOKENS
print(json.dumps({'modelParams': p}))")

  echo "Model '$MODEL_ALIAS' ($MODEL_ID)"
  echo "  current modelParams: $CURRENT"
  if [ "$CURRENT_MAX" = "$MAX_TOKENS" ]; then
    echo "  already max_tokens=$MAX_TOKENS - unchanged."
    continue
  fi
  echo "  intended:            $(printf '%s' "$NEW_PARAMS" | python3 -c 'import sys,json;print(json.dumps(json.load(sys.stdin)["modelParams"]))')"
  [ "$DRY_RUN" -eq 1 ] && continue

  # --- PATCH (merge; authConfig untouched) --------------------------
  APPLIED=$(printf '%s' "$NEW_PARAMS" \
    | sam_cli_api -X PATCH "/api/v1/platform/models/$MODEL_ID" --input - 2>/dev/null \
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
    echo "ERROR: PATCH did not apply max_tokens=$MAX_TOKENS on '$MODEL_ALIAS' (got: '${APPLIED:-no response}')." >&2
    # Stop patching, but still restart below if an earlier alias
    # was changed -- otherwise that change would never take effect.
    PATCH_FAILED=1
    break
  fi
  echo "  max_tokens set to $MAX_TOKENS."
  CHANGED=1
done

if [ "$DRY_RUN" -eq 1 ]; then
  echo "DRY RUN - nothing changed."
  exit 0
fi
if [ "$CHANGED" -eq 0 ]; then
  if [ "$PATCH_FAILED" -eq 1 ]; then
    exit 1
  fi
  echo "Nothing changed - no restart needed."
  exit 0
fi

# --- Restart the Agent-Workflow Executor ----------------------------
# Agents (and workflows) run in the awe deployment and read the
# model configuration at startup via the model bootstrap queues.
RESTART_CMD="kubectl rollout restart deployment -n $SAM_NAMESPACE -l app.kubernetes.io/component=awe"
if [ -n "${SAM_URL:-}" ]; then
  # Remote platform (SAM_URL; e.g. AKS via aks_sam): a bare kubectl
  # in a message would hit whatever context is current in the shell
  # it is pasted into -- often the lab. Name the target instead.
  SAM_HOST="${SAM_URL#*://}"; SAM_HOST="${SAM_HOST%%/*}"; SAM_HOST="${SAM_HOST%%:*}"
  RESTART_CMD="kubectl --kubeconfig <kubeconfig of $SAM_HOST> --context <its context> rollout restart deployment -n $SAM_NAMESPACE -l app.kubernetes.io/component=awe
  (AKS: kaks -n $SAM_NAMESPACE rollout restart deployment -l app.kubernetes.io/component=awe)"
fi
if [ "$RESTART" -eq 0 ]; then
  echo "Skipped restart (--no-restart). Apply it later with:"
  echo "  $RESTART_CMD"
  exit "$PATCH_FAILED"
fi

if [ -z "${SAM_URL:-}" ]; then
  # --- Lab: the current kubectl context, as always -------------------
  if ! command -v kubectl >/dev/null 2>&1 || ! kubectl get ns "$SAM_NAMESPACE" >/dev/null 2>&1; then
    echo "kubectl/namespace not reachable - restart the agents manually:"
    echo "  $RESTART_CMD"
    exit "$PATCH_FAILED"
  fi
  echo "Restarting the Agent-Workflow Executor ..."
  kubectl rollout restart deployment -n "$SAM_NAMESPACE" -l app.kubernetes.io/component=awe
  kubectl rollout status deployment -n "$SAM_NAMESPACE" -l app.kubernetes.io/component=awe --timeout=300s || true
  echo "Done - agents re-read the model config on startup."
  exit "$PATCH_FAILED"
fi

# --- Remote platform: restart only on a cluster PROVEN to serve it ---
# Fail closed: KUBECONFIG must name exactly one kubeconfig file (aks_sam
# sets the AKS file), its current context must not be the lab, and an
# Ingress in SAM_NAMESPACE of that cluster must serve the SAM_URL host.
# Every kubectl call is then pinned to that file and context. This
# restart happens once, and only when a max_tokens PATCH changed
# something -- on a remote platform that is the first provision.sh
# after an install or rebuild (runbook A17 / 4.7), never a re-run.
remote_kube_target() {
  local hosts
  case "${KUBECONFIG:-}" in
    "")  echo "  KUBECONFIG is not set (it must name the target cluster's kubeconfig file)."; return 1 ;;
    *:*) echo "  KUBECONFIG lists several files (it must name exactly one)."; return 1 ;;
  esac
  [ -f "$KUBECONFIG" ] || { echo "  kubeconfig $KUBECONFIG not found."; return 1; }
  command -v kubectl >/dev/null 2>&1 || { echo "  kubectl not found."; return 1; }
  KCTX=$(kubectl --kubeconfig "$KUBECONFIG" config current-context 2>/dev/null) || KCTX=""
  case "$KCTX" in
    "")              echo "  no current context in $KUBECONFIG."; return 1 ;;
    rancher-desktop) echo "  the current context of $KUBECONFIG is the lab (rancher-desktop)."; return 1 ;;
  esac
  hosts=$(kubectl --kubeconfig "$KUBECONFIG" --context "$KCTX" -n "$SAM_NAMESPACE" \
    get ingress -o jsonpath='{.items[*].spec.rules[*].host}' 2>/dev/null) || hosts=""
  case " $hosts " in
    *" $SAM_HOST "*) return 0 ;;
  esac
  echo "  no Ingress in $SAM_NAMESPACE on context $KCTX serves $SAM_HOST."
  return 1
}
KCTX=""
if ! remote_kube_target; then
  echo "Not restarting the agents: the kubectl target is not proven to"
  echo "serve $SAM_URL. Restart awe on the cluster that serves it:"
  echo "  $RESTART_CMD"
  [ "$PATCH_FAILED" -eq 1 ] && exit 1
  exit 2   # provision.sh reports WARN
fi
echo "Restarting the Agent-Workflow Executor on context $KCTX ($SAM_HOST) ..."
kubectl --kubeconfig "$KUBECONFIG" --context "$KCTX" rollout restart deployment \
  -n "$SAM_NAMESPACE" -l app.kubernetes.io/component=awe
kubectl --kubeconfig "$KUBECONFIG" --context "$KCTX" rollout status deployment \
  -n "$SAM_NAMESPACE" -l app.kubernetes.io/component=awe --timeout=300s || true
echo "Done - agents re-read the model config on startup."
exit "$PATCH_FAILED"
