#!/bin/bash
# Shared helpers for install.sh / uninstall.sh / reset.sh.
# Source this file; reuses ../../agent-mesh-deployment/scripts/lib/common.sh
# (load_env, resolve_sam_cli, sam_auth_token) like the other demos.

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AMD="$(cd "$DEMO_DIR/../agent-mesh-deployment" && pwd)"
NS=bsg-demo
SAM_URL="${SAM_URL:-https://sam.solace.lab}"
API_BODY="${TMPDIR:-/tmp}/bsg-api-body.json"

# shellcheck source=/dev/null
. "$AMD/scripts/lib/common.sh"
load_env "$DEMO_DIR"

sam_login() {  # resolve the CLI and a fresh token (CLI call refreshes the cache)
  resolve_sam_cli || return 1
  (cd "$DEMO_DIR/mesh" && "$SAM_CLI" config plan >/dev/null 2>&1) || true
  sam_auth_token
}

api() {  # api METHOD PATH -> body on stdout, HTTP code in API_CODE
  local method="$1" path="$2"
  [ "$method" = GET ] && case "$path" in *\?*) ;; *) path="$path?pageSize=100" ;; esac
  API_CODE=$(curl -sk -m 20 -X "$method" "$SAM_URL$path" \
    -H "Authorization: Bearer $SAM_AUTH_TOKEN" \
    -o "$API_BODY" -w "%{http_code}") || API_CODE=000
  cat "$API_BODY" 2>/dev/null || true
}

id_of() {  # id_of PATH NAME -> platform id of the named resource ("" if absent)
  api GET "$1" | python3 -c "
import json,sys
try:
    for x in json.load(sys.stdin).get('data',[]):
        if x.get('name')==sys.argv[1]: print(x['id'])
except Exception: pass" "$2"
}

delete_named() {  # delete_named LABEL PATH NAME
  local label="$1" path="$2" name="$3" id
  id=$(id_of "$path" "$name")
  if [ -z "$id" ]; then echo "   $label '$name': not present"; return 0; fi
  api DELETE "$path/$id" >/dev/null
  case "$API_CODE" in
    2??) echo "   $label '$name': deleted" ;;
    *)   echo "   WARNING: $label '$name': DELETE failed (HTTP $API_CODE)" ;;
  esac
}

ui_exec() {  # run bsgctl inside the demo-ui pod (has broker env + Secret)
  kubectl -n "$NS" exec deploy/demo-ui -- python -m bsgdemo.ctl "$@"
}
