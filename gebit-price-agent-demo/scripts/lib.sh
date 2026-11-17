#!/bin/bash
# lib.sh -- shared helpers of the gpos demo scripts (spec 12.6). Source it.
# Reuses ../agent-mesh-deployment/scripts/lib/common.sh (load_env,
# resolve_sam_cli, sam_auth_token) like the BSG demo. load_env reads ONLY the
# .env of this demo: the .env of agent-mesh-deployment carries the LLM key,
# and `sam config apply` expands ${VAR} from the process environment (G0-05).

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AMD="$(cd "$DEMO_DIR/../agent-mesh-deployment" && pwd)"

# shellcheck source=/dev/null
. "$AMD/scripts/lib/common.sh"
load_env "$DEMO_DIR"

NS="${GPOS_NS:-gpos-demo}"
SAM_URL="${SAM_URL:-https://sam.solace.lab}"
PG_CONTAINER="${PG_CONTAINER:-postgres}"
PG_DB="${PG_DB:-gpos}"
RENDERED="$DEMO_DIR/mesh/.rendered"
BUILD_DIR="$DEMO_DIR/build"
DEPLOYMENTS="gpos-pos gpos-wws gpos-loyalty gpos-engine gpos-gate gpos-ui"
if [ -x "$DEMO_DIR/.venv/bin/python" ]; then
  PY="$DEMO_DIR/.venv/bin/python"
else
  PY="$(command -v python3)"
fi

die() { echo "ERROR: $*" >&2; exit 1; }
step() { printf '== %s\n' "$*"; }

sam_login() {  # resolve the CLI, refresh its token cache, export SAM_AUTH_TOKEN
  resolve_sam_cli || return 1
  # a read-only CLI call refreshes the OAuth cache (BSG pattern); never --prune
  (cd "$DEMO_DIR/mesh" && "$SAM_CLI" config plan --no-dotenv --no-interactive \
    >/dev/null 2>&1) || true
  sam_auth_token
}

sam_apply() {  # sam_apply DIR [MANIFEST] -- the only way this demo applies config
  local dir="$1" manifest="${2:-manifest.yaml}"
  case " $* " in *" --prune "*) die "sam config apply --prune is forbidden (hard rule 3)";; esac
  (cd "$dir" && "$SAM_CLI" config apply --no-dotenv --no-interactive -m "$manifest")
}

api() {  # api METHOD PATH [BODY_JSON] -> body on stdout, HTTP code in API_CODE
  local method="$1" path="$2" body="${3:-}" out
  out="$(mktemp "${TMPDIR:-/tmp}/gpos-api.XXXXXX")"
  local args=(-sS -m 20 -X "$method" "$SAM_URL$path" -o "$out" -w '%{http_code}'
              --config -)
  [ -n "$body" ] && args+=(-H 'Content-Type: application/json' --data-binary "$body")
  # the token goes through stdin (curl --config -), never into argv
  API_CODE=$(printf 'header = "Authorization: Bearer %s"\n' "$SAM_AUTH_TOKEN" \
    | curl "${args[@]}") || API_CODE=000
  cat "$out" 2>/dev/null || true
  rm -f "$out"
}

id_of() {  # id_of PATH NAME -> platform id of the named resource ("" if absent)
  api GET "$1?pageSize=100" | python3 -c "
import json, sys
try:
    for x in json.load(sys.stdin).get('data', []):
        if x.get('name') == sys.argv[1]:
            print(x['id'])
except Exception:
    pass" "$2"
}

delete_named() {  # delete_named LABEL PATH NAME (BSG pattern)
  local label="$1" path="$2" name="$3" id
  id=$(id_of "$path" "$name")
  if [ -z "$id" ]; then echo "   $label '$name': not present"; return 0; fi
  api DELETE "$path/$id" >/dev/null
  case "$API_CODE" in
    2??) echo "   $label '$name': deleted" ;;
    *)   echo "   WARNING: $label '$name': DELETE failed (HTTP $API_CODE)" ;;
  esac
}

psql_admin() {  # psql as the container superuser over the local socket
  docker exec -i "$PG_CONTAINER" psql -X -U postgres -v ON_ERROR_STOP=1 "$@"
}

ui_ctl() {  # gposdemo.ui.ctl inside deploy/gpos-ui (cluster DNS, broker Secret)
  kubectl -n "$NS" exec deploy/gpos-ui -- python -m gposdemo.ui.ctl "$@"
}

hygiene_or_die() {
  "$DEMO_DIR/scripts/check_hygiene.sh" || die "check_hygiene.sh failed -- refusing to start"
}
