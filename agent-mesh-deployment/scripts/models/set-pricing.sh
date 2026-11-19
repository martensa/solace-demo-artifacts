#!/bin/bash
set -euo pipefail

# =============================================================
# set-pricing.sh (SAM v2) -- set token rates (pricing) on model
# configurations via the platform API.
# =============================================================
# Token governance (feature flag token_governance, on by default
# in 2.542.1) only computes spend, cost views and budgets for a
# model that has a price; an unpriced model counts as free, so a
# budget never trips. The declarative `kind: model` has no pricing
# field, so this runs after apply-models.sh (provision.sh step).
#
# Rates are US dollars per million tokens as decimal strings
# (input, output, cacheRead, cacheWrite = 5-minute cache write).
# They are Anthropic list prices for the upstream model (checked
# 2026-11-11); the LiteLLM proxy bills its own way, so treat the
# platform cost as an estimate. An alias already at the target
# rates is left alone; re-running is a no-op.
#
# Auth: sam CLI login cache (sam auth login solace-lab ...), the
# token is exported as SAM_AUTH_TOKEN by scripts/lib/common.sh.
#
# Optional environment (unset = the local lab): SAM_ENV_FILE,
# SAM_HOME, SAM_URL -- see scripts/lib/common.sh.
# =============================================================

usage() {
  cat <<'USAGE'
Usage:
  ./set-pricing.sh            # price every alias in PRICES below
  ./set-pricing.sh --dry-run  # show current + intended, no change
USAGE
}

# alias -> "input output cacheRead cacheWrite" (USD per 1M tokens)
declare -a PRICES=(
  "fast 1 5 0.1 1.25"         # Claude Haiku 4.5
  "workflow 2 10 0.2 2.5"     # Claude Sonnet 5
  "planning 2 10 0.2 2.5"     # Claude Sonnet 5
)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DRY_RUN=0
case "${1:-}" in
  --dry-run) DRY_RUN=1 ;;
  -h|--help) usage; exit 0 ;;
  "") ;;
  *) echo "Unknown argument: $1" >&2; usage >&2; exit 1 ;;
esac

# shellcheck source=../lib/common.sh
. "$PROJECT_DIR/scripts/lib/common.sh"
load_env "$PROJECT_DIR" "${SAM_ENV_FILE:-$PROJECT_DIR/.env}"
sam_target_check "$PROJECT_DIR" || exit 1
resolve_sam_cli
sam_auth_token

# The EA sam CLI prints log lines on stdout; keep the JSON only.
json_only() {
  python3 -c "
import sys
print(''.join(l for l in sys.stdin if l.lstrip().startswith(('{','['))))"
}

MODELS_JSON=$(sam_cli_api /api/v1/platform/models 2>/dev/null | json_only \
  | python3 -c "
import sys, json
d = json.loads(sys.stdin.read())
rows = d.get('data') if isinstance(d, dict) else d
if not isinstance(rows, list) or (isinstance(d, dict) and d.get('errorType')):
    raise SystemExit(1)
print(json.dumps(rows))" 2>/dev/null || true)
[ -n "$MODELS_JSON" ] || {
  echo "ERROR: could not list the platform models (token expired?" >&2
  echo "Re-run: $(sam_login_cmd))" >&2
  exit 1; }

FAILED=0
for entry in "${PRICES[@]}"; do
  read -r ALIAS IN OUT CR CW <<<"$entry"
  MODEL_ID=$(printf '%s' "$MODELS_JSON" | python3 -c "
import sys, json
m = next((r for r in json.load(sys.stdin)
          if (r.get('alias') or r.get('name')) == sys.argv[1]), None)
print(m['id'] if m else '')" "$ALIAS")
  if [ -z "$MODEL_ID" ]; then
    echo "WARNING: model alias '$ALIAS' not found - skipped." >&2
    FAILED=1; continue
  fi
  BODY=$(python3 -c "
import json, sys
a = sys.argv[1:]
print(json.dumps({'pricing': {'input': a[0], 'output': a[1],
                              'cacheRead': a[2], 'cacheWrite': a[3]}}))" \
    "$IN" "$OUT" "$CR" "$CW")
  CURRENT=$(sam_cli_api "/api/v2/platform/models/$MODEL_ID" 2>/dev/null | json_only \
    | python3 -c "
import sys, json
d = json.loads(sys.stdin.read()); d = d.get('data', d)
print(json.dumps(d.get('pricing'), sort_keys=True))" 2>/dev/null || echo "?")
  WANT=$(printf '%s' "$BODY" | python3 -c "
import sys, json
from decimal import Decimal
p = json.load(sys.stdin)['pricing']
print(json.dumps({k: format(Decimal(v).normalize(), 'f') for k, v in p.items()}, sort_keys=True))")
  NORM_CURRENT=$(printf '%s' "$CURRENT" | python3 -c "
import sys, json
from decimal import Decimal
p = json.loads(sys.stdin.read() or 'null')
print(json.dumps({k: format(Decimal(v).normalize(), 'f') for k, v in (p or {}).items() if v is not None}, sort_keys=True) if p else 'null')" 2>/dev/null || echo "?")
  echo "Model '$ALIAS' ($MODEL_ID)"
  echo "  current pricing: $CURRENT"
  if [ "$NORM_CURRENT" = "$WANT" ]; then
    echo "  already at the target rates - unchanged."
    continue
  fi
  echo "  intended:        $WANT"
  [ "$DRY_RUN" -eq 1 ] && continue
  APPLIED=$(printf '%s' "$BODY" \
    | sam_cli_api -X PATCH "/api/v2/platform/models/$MODEL_ID" --input - 2>/dev/null \
    | json_only | python3 -c "
import sys, json
from decimal import Decimal
d = json.loads(sys.stdin.read()); d = d.get('data', d)
p = d.get('pricing') or {}
print(json.dumps({k: format(Decimal(v).normalize(), 'f') for k, v in p.items() if v is not None}, sort_keys=True))" 2>/dev/null || true)
  if [ "$APPLIED" != "$WANT" ]; then
    echo "ERROR: pricing on '$ALIAS' not applied (got: '${APPLIED:-no response}')." >&2
    echo "       Token governance off? (SAM_FEATURE_TOKEN_GOVERNANCE)" >&2
    FAILED=1; continue
  fi
  echo "  pricing set."
done

[ "$DRY_RUN" -eq 1 ] && echo "DRY RUN - nothing changed."
exit "$FAILED"
