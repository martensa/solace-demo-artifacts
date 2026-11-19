#!/bin/bash
# lib.sh -- shared helpers of the gpos demo scripts (spec 12.6). Source it.
# Reuses ../agent-mesh-deployment/scripts/lib/common.sh (load_env,
# resolve_sam_cli, sam_auth_token) like the BSG demo. load_env reads ONLY the
# .env of this demo: the .env of agent-mesh-deployment carries the LLM key,
# and `sam config apply` expands ${VAR} from the process environment (G0-05).
#
# Target switch (AKS-MIGRATION-PLAN 1.4): TARGET=lab (default) or aks.
#   lab  everything as before: .env, the current kubectl context, docker psql,
#        mesh/.rendered, build/.
#   aks  .env.aks only (never .env); refuses SAM_ENV_FILE, the LLM key variable
#        and KEYCLOAK_CLIENT_SECRET in the environment and every lab-like URL;
#        kubectl is a function bound to AKS_KUBECONFIG + KUBE_CONTEXT (API
#        server checked); the sam CLI runs with HOME=$SAM_HOME of .env.aks (its
#        own login cache) and --url SAM_URL, never with a token of the shell;
#        psql via kubectl exec (PG_MODE=kubectl); mesh/.rendered/aks, build/aks;
#        secrets only at runtime from the Key Vault (kv_secret, pipes only).
#   The sam CLI (2.542.1) keeps its OAuth login cache in
#   $HOME/Library/Application Support/sam/auth/<target>.json and ignores SAM_HOME
#   and --sam-home for it; only another HOME separates the AKS login from the lab.

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AMD="$(cd "$DEMO_DIR/../agent-mesh-deployment" && pwd)"

die() { echo "ERROR: $*" >&2; exit 1; }
step() { printf '== %s\n' "$*"; }

# shellcheck source=/dev/null
. "$AMD/scripts/lib/common.sh"

TARGET="${TARGET:-lab}"
GPOS_SELECTED_TARGET="$TARGET"   # an env file never switches the target
# an AKS API server; anything else (rancher-desktop, a stray context) is refused
AKS_API_SERVER_PATTERN='https://aks-eurocis-*.hcp.germanywestcentral.azmk8s.io:443'
# variables that carry lab or amd secrets into an aks run; the LLM key's name is
# spelled in two parts (scripts/check_hygiene.sh is the only file that names it)
AKS_REFUSED_ENV="SAM_ENV_FILE LLM_SERVICE_""API_KEY KEYCLOAK_CLIENT_SECRET"

_gpos_abs_dir() {  # physical path of an existing directory, else the path without a trailing /
  (CDPATH='' cd "$1" 2>/dev/null && pwd -P) || printf '%s' "${1%/}"
}

aks_env_check() {  # refusals and lab-URL guard of TARGET=aks; names keys, never values
  local key val low home errors=""
  for key in $AKS_REFUSED_ENV; do
    if [ -n "${!key+x}" ]; then
      errors="$errors; $key is set (aks never uses the lab or amd env: fresh shell)"
    fi
  done
  # URL-ish values whose defaults are lab values: required, never lab-like
  for key in SAM_URL E2E_BASE_URL BROKER_SMF_URL BROKER_WS_URL SEMP_URL \
             PG_HOST_FROM_PODS E2E_CA_FILE; do
    val="${!key:-}"
    if [ -z "$val" ]; then
      errors="$errors; $key missing in .env.aks"
      continue
    fi
    low="$(printf '%s' "$val" | tr '[:upper:]' '[:lower:]')"
    case "$low" in
      *solace.lab*|*host.docker.internal*|*localhost*|*:8080*)
        errors="$errors; $key points to the lab" ;;
    esac
  done
  for key in SAM_URL E2E_BASE_URL; do
    case "${!key:-https://}" in https://*) ;; *) errors="$errors; $key must be https://" ;; esac
  done
  case "${E2E_CA_FILE:-}" in *lab-ca*) errors="$errors; E2E_CA_FILE is the lab CA" ;; esac
  for key in AKS_KUBECONFIG KUBE_CONTEXT; do
    [ -n "${!key:-}" ] || errors="$errors; $key missing in .env.aks"
  done
  [ "${PG_MODE:-}" = kubectl ] || errors="$errors; PG_MODE must be kubectl"
  # the only namespaces and pod this demo creates, uses and deletes on AKS (runbook 1.4)
  [ "${GPOS_NS:-gpos-demo}" = gpos-demo ] || errors="$errors; GPOS_NS must be gpos-demo"
  [ "${PG_NS:-}" = gpos-data ] || errors="$errors; PG_NS must be gpos-data"
  [ "${PG_POD:-}" = gpos-postgres-0 ] || errors="$errors; PG_POD must be gpos-postgres-0"
  # SAM_HOME is the HOME of the AKS sam CLI (its login cache): never the real HOME
  # (the lab login) nor the lab sam home
  home="${SAM_HOME:-}"
  if [ -z "$home" ]; then
    errors="$errors; SAM_HOME missing in .env.aks (own sam login cache for AKS)"
  else
    case "$home" in /*) ;; *) errors="$errors; SAM_HOME must be an absolute path" ;; esac
    if [ "$(_gpos_abs_dir "$home")" = "$(_gpos_abs_dir "$HOME")" ]; then
      errors="$errors; SAM_HOME is the real HOME (the sam CLI would use the lab login cache)"
    elif [ "$(_gpos_abs_dir "$home")" = \
           "$(_gpos_abs_dir "$HOME/Library/Application Support/sam")" ]; then
      errors="$errors; SAM_HOME is the lab sam home (AKS needs its own login cache)"
    fi
  fi
  case "${GPOS_IMAGE:-}" in *solace.lab*) errors="$errors; GPOS_IMAGE is a lab image" ;; esac
  [ -z "$errors" ] && return 0
  echo "ERROR: TARGET=aks refused: ${errors#; }" >&2
  return 1
}

case "$TARGET" in
  lab)
    # aks_sam/aks_kc (infra/aks/aks.sh) export SAM_ENV_FILE with KUBECONFIG = the AKS
    # file: a lab run there would apply the lab .env to AKS
    [ -z "${SAM_ENV_FILE+x}" ] || die "TARGET=lab inside an AKS subshell (SAM_ENV_FILE is" \
      "set, aks_sam/aks_kc): run TARGET=aks scripts/... in a plain shell"
    load_env "$DEMO_DIR"
    ENV_NAME=.env
    ;;
  aks)
    for _key in $AKS_REFUSED_ENV; do
      [ -z "${!_key+x}" ] || die "TARGET=aks refused: $_key is set in the environment" \
        "(aks never uses the lab or amd env; open a fresh shell)"
    done
    unset _key
    [ -f "$DEMO_DIR/.env.aks" ] || die "TARGET=aks: $DEMO_DIR/.env.aks missing" \
      "(template infra/aks/env.aks.example, runbook 1.3)"
    load_env "$DEMO_DIR" "$DEMO_DIR/.env.aks"
    # the optional ZeroSSL key of .env.aks is for zerossl_on (infra/aks/aks.sh) only;
    # load_env exported it, and no child process of these scripts gets it
    unset ACME_EAB_HMAC
    ENV_NAME=.env.aks
    aks_env_check || exit 1
    export SAM_HOME
    # no token of the shell reaches an AKS run (sam CLI, curl, Python children): only
    # sam_login exports SAM_AUTH_TOKEN, from the AKS login cache
    unset SAM_AUTH_TOKEN SAM_PLATFORM_TOKEN
    ;;
  *) die "TARGET must be lab or aks (got '$TARGET')" ;;
esac
TARGET="$GPOS_SELECTED_TARGET"
# exported for the Python children on aks only: in the lab their environment stays as
# it was before the switch (opslib reads a missing TARGET as lab)
if [ "$TARGET" = aks ]; then export TARGET; fi

NS="${GPOS_NS:-gpos-demo}"
SAM_URL="${SAM_URL:-https://sam.solace.lab}"
PG_CONTAINER="${PG_CONTAINER:-postgres}"
PG_DB="${PG_DB:-gpos}"
PG_NS="${PG_NS:-gpos-data}"
PG_POD="${PG_POD:-gpos-postgres-0}"
RENDERED="$DEMO_DIR/mesh/.rendered"
BUILD_DIR="$DEMO_DIR/build"
DEPLOYMENTS="gpos-pos gpos-wws gpos-loyalty gpos-engine gpos-gate gpos-ui"
if [ -x "$DEMO_DIR/.venv/bin/python" ]; then
  PY="$DEMO_DIR/.venv/bin/python"
else
  PY="$(command -v python3)"
fi
# extra arguments of every `sam config plan/apply` (empty in the lab: argv as before)
SAM_TARGET_ARGS=()

if [ "$TARGET" = aks ]; then
  RENDERED="$RENDERED/aks"
  BUILD_DIR="$BUILD_DIR/aks"
  SAM_TARGET_ARGS=(--url "$SAM_URL")

  kubectl() {  # kubectl bound to the AKS kubeconfig and context (never the current context)
    if [ ! -f "$AKS_KUBECONFIG" ]; then
      echo "ERROR: AKS kubeconfig $AKS_KUBECONFIG missing (runbook A4)" >&2
      return 1
    fi
    if [ -z "${GPOS_AKS_SERVER_OK:-}" ]; then
      local server
      server="$(command kubectl --kubeconfig "$AKS_KUBECONFIG" --context "$KUBE_CONTEXT" \
        config view --minify -o 'jsonpath={.clusters[0].cluster.server}' 2>/dev/null)" \
        || server=""
      # shellcheck disable=SC2254 # the pattern is meant to glob
      case "$server" in
        $AKS_API_SERVER_PATTERN) GPOS_AKS_SERVER_OK=1 ;;
        *) echo "ERROR: context $KUBE_CONTEXT in $AKS_KUBECONFIG is not the AKS cluster" \
             "(API server ${server:-unknown})" >&2
           return 1 ;;
      esac
    fi
    command kubectl --kubeconfig "$AKS_KUBECONFIG" --context "$KUBE_CONTEXT" "$@"
  }

  # overrides common.sh: the cache the CLI writes when it runs with HOME=$SAM_HOME
  sam_auth_cache_path() {
    printf '%s/Library/Application Support/sam/auth/solace-lab.json\n' "$SAM_HOME"
  }
fi

sam_cli() {  # sam_cli ARGS -- "$SAM_CLI" ARGS; aks: HOME=$SAM_HOME, no token of the shell
  if [ "$TARGET" = aks ]; then
    env -u SAM_AUTH_TOKEN -u SAM_PLATFORM_TOKEN HOME="$SAM_HOME" "$SAM_CLI" "$@"
  else
    "$SAM_CLI" "$@"
  fi
}

sam_login() {  # resolve the CLI, refresh its token cache, export SAM_AUTH_TOKEN
  resolve_sam_cli || return 1
  # a read-only CLI call refreshes the OAuth cache (BSG pattern); never --prune
  (cd "$DEMO_DIR/mesh" && sam_cli config plan --no-dotenv --no-interactive \
    ${SAM_TARGET_ARGS[@]+"${SAM_TARGET_ARGS[@]}"} >/dev/null 2>&1) || true
  if [ "$TARGET" = aks ] && [ ! -f "$(sam_auth_cache_path)" ]; then
    # never the plain `sam auth login` of the lab hint: it would overwrite the lab login
    echo "ERROR: no AKS sam login ($(sam_auth_cache_path) missing). Log in first" \
      "(runbook A17):" >&2
    echo "  aks_sam sam auth login solace-lab --url $SAM_URL" >&2
    echo "  (the sam CLI must run with HOME=$SAM_HOME)" >&2
    return 1
  fi
  sam_auth_token
}

sam_apply() {  # sam_apply DIR [MANIFEST] -- the only way this demo applies config
  local dir="$1" manifest="${2:-manifest.yaml}"
  case " $* " in *" --prune "*) die "sam config apply --prune is forbidden (hard rule 3)";; esac
  (cd "$dir" && sam_cli config apply --no-dotenv --no-interactive -m "$manifest" \
    ${SAM_TARGET_ARGS[@]+"${SAM_TARGET_ARGS[@]}"})
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

psql_admin() {  # psql as the superuser over the local socket (PG_MODE docker|kubectl)
  if [ "${PG_MODE:-docker}" = kubectl ]; then
    kubectl -n "$PG_NS" exec -i "$PG_POD" -- psql -X -U postgres -v ON_ERROR_STOP=1 "$@"
  else
    docker exec -i "$PG_CONTAINER" psql -X -U postgres -v ON_ERROR_STOP=1 "$@"
  fi
}

pg_ready() {  # 0 when the target's Postgres runs (docker: container; kubectl: pg_isready)
  if [ "${PG_MODE:-docker}" = kubectl ]; then
    kubectl -n "$PG_NS" exec "$PG_POD" -- pg_isready -q -U postgres -t 5 >/dev/null 2>&1
  else
    docker inspect -f '{{.State.Running}}' "$PG_CONTAINER" 2>/dev/null | grep -q true
  fi
}

kv_secret() {  # kv_secret NAME -> Key Vault secret value on stdout without newline (pipes only)
  if [ "$TARGET" != aks ]; then
    echo "ERROR: kv_secret only with TARGET=aks" >&2
    return 1
  fi
  if [ -z "${AKS_KV:-}" ]; then
    echo "ERROR: AKS_KV is empty in .env.aks" >&2
    return 1
  fi
  # never captured, echoed or traced: az -> tr -> the caller's pipe
  az keyvault secret show --vault-name "$AKS_KV" -n "$1" --query value -o tsv | tr -d '\r\n'
  return "${PIPESTATUS[0]}"
}

apply_acr_pull() {  # apply_acr_pull NS -- Secret acr-pull (ACR token aks-pull) via pipes only
  if [ "$TARGET" != aks ] || [ -z "${AKS_ACR:-}" ]; then
    echo "ERROR: apply_acr_pull needs TARGET=aks and AKS_ACR in .env.aks" >&2
    return 1
  fi
  # jq refuses an empty token, so a failed Key Vault read never becomes a valid Secret
  kv_secret acr-pull-token \
    | jq -Rsc --arg s "$AKS_ACR.azurecr.io" --arg u "${ACR_PULL_USER:-aks-pull}" \
        'if . == "" then error("empty ACR token") else
         {auths: {($s): {username: $u, password: ., auth: (($u + ":" + .) | @base64)}}} end' \
    | kubectl -n "$1" create secret generic acr-pull --type=kubernetes.io/dockerconfigjson \
        --from-file=.dockerconfigjson=/dev/stdin --dry-run=client -o yaml \
    | kubectl apply --server-side --force-conflicts --field-manager=gpos-install -f - >/dev/null
}

apply_broker_secret() {  # apply_broker_secret NS -- aks: Secret gpos-broker via pipes only
  if [ "$TARGET" != aks ] || [ -z "${BROKER_USERNAME:-}" ] \
     || [ -z "${BROKER_PASSWORD_KV:-}" ] || [ -z "${BROKER_SMF_URL:-}" ]; then
    echo "ERROR: apply_broker_secret needs TARGET=aks and BROKER_SMF_URL, BROKER_USERNAME," \
      "BROKER_PASSWORD_KV in .env.aks" >&2
    return 1
  fi
  # the SOLACE_* keys of render_mesh.py --write-broker-env (lab), but no file: jq builds
  # the whole Secret from the Key Vault value on stdin and emits nothing for an empty
  # one, so a failed Key Vault read applies nothing (kubectl apply gets no object)
  kv_secret "$BROKER_PASSWORD_KV" \
    | jq -Rsc --arg ns "$1" --arg host "$BROKER_SMF_URL" --arg vpn "${BROKER_VPN:-default}" \
        --arg user "$BROKER_USERNAME" \
        'if . == "" then error("empty broker password from the Key Vault") else
         {apiVersion: "v1", kind: "Secret", type: "Opaque",
          metadata: {name: "gpos-broker", namespace: $ns},
          data: {SOLACE_HOST: ($host | @base64), SOLACE_VPN: ($vpn | @base64),
                 SOLACE_USERNAME: ($user | @base64), SOLACE_PASSWORD: (. | @base64)}} end' \
    | kubectl apply --server-side --force-conflicts --field-manager=gpos-install -f - >/dev/null
}

ui_ctl() {  # gposdemo.ui.ctl inside deploy/gpos-ui (cluster DNS, broker Secret)
  kubectl -n "$NS" exec deploy/gpos-ui -- python -m gposdemo.ui.ctl "$@"
}

hygiene_or_die() {
  "$DEMO_DIR/scripts/check_hygiene.sh" || die "check_hygiene.sh failed -- refusing to start"
}
