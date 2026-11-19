#!/bin/bash
set -euo pipefail

# =============================================================
# apply-models.sh -- create/update the additional LLM models
# (workflow, reasoning, coding, expert, fast, google gemini)
# declaratively and probe every model's upstream with a tiny call
# afterwards.
# =============================================================
# Idempotent: `sam config apply` creates or updates; re-running
# is safe. Run by ../provision.sh (which start.sh calls in a
# terminal) and by the demo install scripts; usable standalone.
#
# Auth: needs a sam CLI login (browser flow):
#   sam auth login solace-lab --url https://sam.solace.lab
# The LLM_SERVICE_API_KEY (LiteLLM proxy) and the
# GOOGLE_AI_STUDIO_API_KEY ("google gemini", direct Gemini API)
# for the model specs and the probes are resolved from the repo
# .env (or $SAM_ENV_FILE). The LLM key is required; without the
# Google key the "google gemini" alias is skipped with a warning
# (exit 0 -- the demo installs call this under set -e and must not
# abort).
#
# Optional environment (unset = the local lab): SAM_ENV_FILE,
# SAM_HOME, SAM_URL -- see scripts/lib/common.sh.
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
ENV_FILE="${SAM_ENV_FILE:-$PROJECT_DIR/.env}"
load_env "$PROJECT_DIR" "$ENV_FILE"
sam_target_check "$PROJECT_DIR" || exit 1

if [ -z "${LLM_SERVICE_API_KEY:-}" ] || [ "$LLM_SERVICE_API_KEY" = "changeme" ]; then
  echo "ERROR: LLM_SERVICE_API_KEY is not set in $ENV_FILE" >&2
  exit 1
fi
WITH_GEMINI=1
if [ -z "${GOOGLE_AI_STUDIO_API_KEY:-}" ] || [ "$GOOGLE_AI_STUDIO_API_KEY" = "changeme" ]; then
  WITH_GEMINI=0
  echo "WARNING: GOOGLE_AI_STUDIO_API_KEY is not set in $ENV_FILE --"
  echo "  skipping the \"google gemini\" alias (the other five are applied)."
fi

# --- Apply ----------------------------------------------------------
if [ "$PROBE_ONLY" -eq 0 ]; then
  resolve_sam_cli
  echo "Applying additional models (workflow, reasoning, coding," \
       "expert, fast$([ "$WITH_GEMINI" -eq 1 ] && echo ', google gemini')) ..."
  if [ "$WITH_GEMINI" -eq 1 ]; then
    (cd "$SCRIPT_DIR" && sam_cli_config apply)
  else
    # An unset ${VAR} fails the WHOLE apply, so apply a copy of the
    # manifest without the gemini entry (same directory: the
    # resolver finds models/ next to the manifest).
    TMP_MANIFEST="$SCRIPT_DIR/.manifest-without-gemini.yaml"
    trap 'rm -f "$TMP_MANIFEST"' EXIT
    grep -v '^    - google gemini$' "$SCRIPT_DIR/manifest.yaml" > "$TMP_MANIFEST"
    (cd "$SCRIPT_DIR" && sam_cli_config apply -m "$(basename "$TMP_MANIFEST")")
  fi
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
# API keys of the probes: the lab passes them as -H in the argv, as
# always (LLM_AUTH / GEMINI_AUTH at the same position). A remote run
# (SAM_ENV_FILE, e.g. AKS) never puts a key into an argv (ps, process
# auditing): key_curl reads the header from a curl config on a file
# descriptor (printf is a builtin) and the arrays stay empty.
if [ -n "${SAM_ENV_FILE:-}" ]; then
  for key_var in LLM_SERVICE_API_KEY GOOGLE_AI_STUDIO_API_KEY; do
    case "${!key_var:-}" in
      *[!A-Za-z0-9._~+/=:-]*)
        echo "ERROR: $key_var has characters a curl config cannot carry." >&2
        exit 1 ;;
    esac
  done
  LLM_AUTH=()
  GEMINI_AUTH=()
else
  LLM_AUTH=(-H "Authorization: Bearer $LLM_SERVICE_API_KEY")
  GEMINI_AUTH=(-H "x-goog-api-key: ${GOOGLE_AI_STUDIO_API_KEY:-}")
fi
key_curl() {   # key_curl HEADER-NAME VALUE CURL-ARGS...
  local name="$1" value="$2"
  shift 2
  if [ -n "${SAM_ENV_FILE:-}" ]; then
    curl --config <(printf 'header = "%s: %s"\n' "$name" "$value") "$@"
  else
    curl "$@"
  fi
}
echo ""
echo "Probing model upstreams (LiteLLM proxy $API_BASE; google gemini direct) ..."
FAILED=0
for entry in "${MODELS[@]}"; do
  alias="${entry%%|*}"
  model="${entry##*|}"
  body=$(key_curl Authorization "Bearer $LLM_SERVICE_API_KEY" \
    -sk -m 90 "$API_BASE/v1/chat/completions" \
    ${LLM_AUTH[@]+"${LLM_AUTH[@]}"} \
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
  printf '  %-14s %-28s %s\n' "$alias" "($model)" "$verdict"
  case "$verdict" in FAIL*) FAILED=1 ;; esac
done

# "google gemini" bypasses the proxy: probe the Gemini API itself.
# Key in a header, never in the URL. Gemini 3.x spends ~70
# "thought" tokens before a one-word answer, so the budget must be
# far above the proxy probes' 32 or the reply comes back empty.
GEMINI_MODEL="gemini-3.6-flash"
if [ "$WITH_GEMINI" -eq 1 ]; then
body=$(key_curl x-goog-api-key "$GOOGLE_AI_STUDIO_API_KEY" -s -m 90 \
  "https://generativelanguage.googleapis.com/v1beta/models/$GEMINI_MODEL:generateContent" \
  ${GEMINI_AUTH[@]+"${GEMINI_AUTH[@]}"} \
  -H "Content-Type: application/json" \
  -d '{"contents":[{"parts":[{"text":"Reply with exactly: OK"}]}],"generationConfig":{"maxOutputTokens":512}}' \
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
elif not d.get('candidates'):
    print('FAIL  no candidates')
else:
    print('OK')")
printf '  %-14s %-28s %s\n' "google gemini" "($GEMINI_MODEL)" "$verdict"
case "$verdict" in FAIL*) FAILED=1 ;; esac
else
  printf '  %-14s %-28s %s\n' "google gemini" "($GEMINI_MODEL)" "SKIPPED (no key)"
fi
if [ "$FAILED" -eq 1 ]; then
  echo ""
  echo "WARNING: at least one model upstream is failing. The model" >&2
  echo "config in SAM is fine -- the backend (LiteLLM proxy or the" >&2
  echo "Gemini API) is rejecting calls. Agents bound to that alias will" >&2
  echo "error until the proxy backend is fixed." >&2
  exit 2
fi
echo "All model upstreams healthy."
