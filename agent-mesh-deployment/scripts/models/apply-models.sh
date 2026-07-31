#!/bin/bash
set -euo pipefail

# =============================================================
# apply-models.sh -- create/update the additional LLM models
# (workflow, reasoning, coding, expert, fast) declaratively and
# probe every model's upstream with a 1-token call afterwards.
# =============================================================
# Idempotent: `sam config apply` creates or updates; re-running
# is safe. Called by start.sh after the pods are ready (one-click
# deployment) and usable standalone.
#
# Auth: needs a sam CLI login (browser flow):
#   sam auth login solace-lab --url https://sam.solace.lab
# The LLM_SERVICE_API_KEY for the model specs and the probes is
# resolved from the repo .env.
#
#   ./apply-models.sh                # apply + probe
#   ./apply-models.sh --probe-only   # pre-flight: probe upstreams
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

PROBE_ONLY=0
case "${1:-}" in
  --probe-only) PROBE_ONLY=1 ;;
  -h|--help)    grep '^#   \./' "$0" | sed 's/^#   //'; exit 0 ;;
  "")           ;;
  *)            echo "Unknown argument: $1" >&2; exit 1 ;;
esac

# --- Shared helpers (env, sam CLI) ---------------------------------
# shellcheck source=../lib/common.sh
. "$PROJECT_DIR/scripts/lib/common.sh"
load_env "$PROJECT_DIR"

if [ -z "${LLM_SERVICE_API_KEY:-}" ] || [ "$LLM_SERVICE_API_KEY" = "changeme" ]; then
  echo "ERROR: LLM_SERVICE_API_KEY is not set in $PROJECT_DIR/.env" >&2
  exit 1
fi

# --- Apply ----------------------------------------------------------
if [ "$PROBE_ONLY" -eq 0 ]; then
  resolve_sam_cli
  echo "Applying additional models (workflow, reasoning, coding," \
       "expert, fast) ..."
  (cd "$SCRIPT_DIR" && "$SAM_CLI" config apply)
fi

# --- Probe every model upstream (1-token calls) ---------------------
# The proxy authenticates every model with this key, but backends
# behind it can rot independently (broken Azure subscription key,
# Google service account) -- a cheap live probe per model catches
# that immediately. Also part of the meetup pre-flight checklist.
API_BASE="https://lite-llm.mymaas.net"
MODELS=(
  "workflow|claude-sonnet-5"
  "reasoning|deepseek.v3.2"
  "coding|qwen.qwen3-coder-next"
  "expert|claude-opus-5"
  "fast|claude-haiku-4-5-20251001"
)
echo ""
echo "Probing model upstreams via $API_BASE ..."
FAILED=0
for entry in "${MODELS[@]}"; do
  alias="${entry%%|*}"
  model="${entry##*|}"
  body=$(curl -sk -m 90 "$API_BASE/v1/chat/completions" \
    -H "Authorization: Bearer $LLM_SERVICE_API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: OK\"}],\"max_tokens\":32}" \
    2>/dev/null || true)
  verdict=$(printf '%s' "$body" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print('FAIL  no/invalid response'); raise SystemExit
if 'error' in d:
    msg = ' '.join(str(d['error'].get('message', d['error'])).split())
    print('FAIL  ' + msg[:80])
else:
    print('OK')")
  printf '  %-10s %-28s %s\n' "$alias" "($model)" "$verdict"
  case "$verdict" in FAIL*) FAILED=1 ;; esac
done
if [ "$FAILED" -eq 1 ]; then
  echo ""
  echo "WARNING: at least one model upstream is failing. The model" >&2
  echo "config in SAM is fine -- the backend behind the LiteLLM" >&2
  echo "proxy is rejecting calls. Agents bound to that alias will" >&2
  echo "error until the proxy backend is fixed." >&2
  exit 2
fi
echo "All model upstreams healthy."
