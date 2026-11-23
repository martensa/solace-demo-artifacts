# gebit-price-agent-demo/infra/aks/aks.sh (core), source it in the repo root
#
# Variables, wrappers and helpers of the AKS runbook
# (gebit-price-agent-demo/AKS-MIGRATION-PLAN.md, sections 1.5 and 1.6).
# Source it in every terminal, in the repo root, before any AKS step:
#
#   . gebit-price-agent-demo/infra/aks/aks.sh
#
# Written for zsh (the operator shell); also parses and runs in bash 3.2.
# Rules this file keeps:
# - Nothing here exports KUBECONFIG or switches the current context: the
#   cluster is reached only through kaks/haks (explicit kubeconfig file and
#   context) or the subshells of aks_sam/aks_kc.
# - Only AKS_ACR and AKS_KV are read from gebit-price-agent-demo/.env.aks
#   into the shell; the fallbacks (OWNER_TAG, CREATED_DATE, ACME_EAB_*) and
#   GRAFANA_ALLOW (grafana_allow) are read on demand, SAM_HOME and SAM_URL
#   only by aks_sam/aks_kc to compare
#   them with AKS_SAM_HOME and https://$FQDN. The LLM key is read only in two
#   subshells: amd_env_aks
#   copies it from file to file, sam_helm hands it to helm on stdin.
# - Secrets move only through pipes, curl config read from a pipe, helm values
#   read from stdin, or the environment of one child process. Never as argv,
#   never on screen: kv and kc_token refuse a terminal as stdout, and every
#   secret-handling helper refuses to run under xtrace (set -x).
# - Helpers fail closed: missing preconditions return 1 with a message on
#   stderr. Nothing calls exit (this file is sourced).
# - Operator messages are German like the runbook (OFFEN, zu, FEHLER).

[ -n "${ZSH_VERSION:-}" ] && setopt interactivecomments
[ -f gebit-price-agent-demo/infra/aks/aks.sh ] ||
  { echo "aks.sh: im Repo-Root sourcen" >&2; return 1; }
# Operator aliases (grep --color=always, kubectl=..., curl=...) must not leak
# into the functions below: alias expansion is off while they are defined and
# restored at the end of this file.
_aks_al=0
if [ -n "${ZSH_VERSION:-}" ]; then
  [[ -o aliases ]] && _aks_al=1 && setopt noaliases
elif shopt -q expand_aliases 2>/dev/null; then
  _aks_al=1 && shopt -u expand_aliases
fi
AKS_DIR=$PWD/gebit-price-agent-demo/infra/aks GPD=$PWD/gebit-price-agent-demo
AMD=$PWD/agent-mesh-deployment SLI=$HOME/Documents/GitHub/solace-lab-infrastructure
AKS_RG=gebit-showcase AKS_NODE_RG=gebit-showcase-nodes AKS_NAME=aks-eurocis
AKS_LOC=germanywestcentral AKS_VERSION=1.36.5 AKS_LABEL=eurocis-showcase
FQDN=eurocis-showcase.germanywestcentral.cloudapp.azure.com
AKS_KUBECONFIG=$HOME/.kube/aks-eurocis.yaml
AKS_CONTEXT=aks-eurocis-admin        # az always appends -admin with --admin
AKS_STATE=$HOME/.config/eurocis-aks AKS_SAM_HOME=$HOME/.config/eurocis-aks/sam
# curlimages/curl:8.23.0, multi-arch index digest (checked 19.11.2026)
CURL_IMG=docker.io/curlimages/curl@sha256:3fb7e13e5d179a845c97d78204f3f1064d1907037f26a3ebf91710571151fd93
# KEY=value from gebit-price-agent-demo/.env.aks (last one wins); tolerates an
# inline " # comment" and surrounding quotes. Values are not expanded.
_aks_env() {
  sed -n "s/^$1=//p" "$GPD/.env.aks" 2>/dev/null | tail -1 |
    sed -e 's/[[:space:]]#.*$//' -e 's/[[:space:]]*$//' \
      -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}
AKS_ACR=$(_aks_env AKS_ACR) AKS_KV=$(_aks_env AKS_KV)
kaks() { KUBECONFIG="$AKS_KUBECONFIG" kubectl --context "$AKS_CONTEXT" "$@"; }
haks() { KUBECONFIG="$AKS_KUBECONFIG" helm --kube-context "$AKS_CONTEXT" "$@"; }

# Local endpoints of the two port-forwards (Mac port 8080 is the LAB broker).
AKS_SEMP_URL=http://127.0.0.1:18080   # kaks -n solace port-forward svc/solace-pubsubplus 18080:8080
AKS_KC_URL=http://127.0.0.1:18081/auth   # kaks -n iam port-forward svc/keycloak 18081:8080

if [ -z "$AKS_ACR" ] || [ -z "$AKS_KV" ]; then
  echo "aks.sh: AKS_ACR oder AKS_KV leer (gebit-price-agent-demo/.env.aks, Runbook 1.3)" >&2
fi

# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

_aks_err() { printf '%s\n' "$*" >&2; }

_aks_noxtrace() {   # secrets would show up in the trace
  case $- in
    *x*) _aks_err "aks.sh: xtrace ist an (set -x); erst 'set +x', Secrets nie unter xtrace"
         return 1 ;;
  esac
  return 0
}

_aks_need_kv() {
  [ -n "${AKS_KV:-}" ] ||
    { _aks_err "aks.sh: AKS_KV fehlt (gebit-price-agent-demo/.env.aks, dann aks.sh neu sourcen)"; return 1; }
  printf '%s\n' "$AKS_KV" | grep -Eqx '[A-Za-z][A-Za-z0-9-]{1,22}[A-Za-z0-9]' ||
    { _aks_err "aks.sh: AKS_KV ist kein gültiger Key-Vault-Name"; return 1; }
}

_aks_need_acr() {
  [ -n "${AKS_ACR:-}" ] ||
    { _aks_err "aks.sh: AKS_ACR fehlt (gebit-price-agent-demo/.env.aks, dann aks.sh neu sourcen)"; return 1; }
  printf '%s\n' "$AKS_ACR" | grep -Eqx '[A-Za-z0-9]{5,50}' ||
    { _aks_err "aks.sh: AKS_ACR ist kein gültiger ACR-Name"; return 1; }
}

_aks_req() {   # _aks_req CALLER NAME VALUE: fail when VALUE is empty
  [ -n "$3" ] || { _aks_err "$1: $2 fehlt"; return 1; }
}

# Escapers for values that go into a curl config or a JSON document. The value
# reaches sed through a pipe (printf is a builtin), never through an argv.
_aks_cq() {   # value -> body of a double-quoted curl config string
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

_aks_js() {   # value -> body of a JSON string, control characters dropped
  printf '%s' "$1" | tr -d '\000-\037' | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

_aks_kc_pf() {   # the port-forward 18081 must reach the AKS Keycloak
  local iss
  iss=$(curl -s --max-time 5 \
    "$AKS_KC_URL/realms/solace-lab/.well-known/openid-configuration" 2>/dev/null |
    jq -r '.issuer // empty' 2>/dev/null)
  [ "$iss" = "https://$FQDN/auth/realms/solace-lab" ] && return 0
  _aks_err "aks.sh: 127.0.0.1:18081 ist nicht der AKS-Keycloak (Issuer '${iss:-keiner}');" \
    "Port-Forward im eigenen Terminal: kaks -n iam port-forward svc/keycloak 18081:8080"
  return 1
}

_aks_kc_userid() {   # _aks_kc_userid TOKEN USER -> Keycloak user id (empty if absent)
  curl -s --max-time 15 \
    --config <(printf 'header = "Authorization: Bearer %s"\n' "$(_aks_cq "$1")") \
    "$AKS_KC_URL/admin/realms/solace-lab/users?username=$2&exact=true" |
    jq -r --arg u "$2" '.[]? | select(.username==$u) | .id' 2>/dev/null | head -1
}

_aks_reg() {   # _aks_reg NAME VALUE: compare VALUE with the register file
  local f="$AKS_STATE/$1" old
  if [ ! -s "$f" ]; then
    (umask 077; printf '%s\n' "$2" > "$f") || return 1
    printf '%s: registriert (%s)\n' "$1" "$2"
    return 0
  fi
  old=$(cat "$f")
  if [ "$old" = "$2" ]; then
    printf '%s: unverändert (%s)\n' "$1" "$2"
    return 0
  fi
  (umask 077
   printf '%s %s %s -> %s\n' "$(date '+%d.%m.%Y %H:%M')" "$1" "$old" "$2" >> "$AKS_STATE/ip-history"
   printf '%s\n' "$2" > "$f")
  _aks_err "ACHTUNG $1 geändert: $old -> $2 (Register neu, alt in $AKS_STATE/ip-history)"
  return 1
}

_aks_power() {   # cluster power state (Running/Stopped/...)
  az aks show -g "$AKS_RG" -n "$AKS_NAME" --query powerState.code -o tsv
}

# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------

aks_guard() {   # before every step against AKS
  local srv mode
  [ -f "$AKS_KUBECONFIG" ] ||
    { _aks_err "aks_guard: $AKS_KUBECONFIG fehlt (A4)"; return 1; }
  srv=$(KUBECONFIG="$AKS_KUBECONFIG" command kubectl config view --minify \
    --context "$AKS_CONTEXT" -o jsonpath='{.clusters[0].cluster.server}' 2>/dev/null) || srv=""
  printf '%s\n' "$srv" |
    grep -Eqx 'https://aks-eurocis-[a-z0-9-]+\.hcp\.germanywestcentral\.azmk8s\.io:443' || {
      _aks_err "aks_guard: Server von $AKS_CONTEXT in $AKS_KUBECONFIG ist '${srv:-?}'," \
        "nicht https://aks-eurocis-*.hcp.germanywestcentral.azmk8s.io:443"
      return 1
    }
  mode=$(stat -f %Lp "$AKS_KUBECONFIG" 2>/dev/null || stat -c %a "$AKS_KUBECONFIG" 2>/dev/null)
  [ "$mode" = 600 ] || _aks_err "aks_guard: WARNUNG $AKS_KUBECONFIG hat Modus ${mode:-?}, soll 600"
  return 0
}

lab_guard() {   # before every lab script (amd, gpd, emd)
  local ctx v
  [ -z "${KUBECONFIG:-}" ] ||
    { _aks_err "lab_guard: KUBECONFIG ist gesetzt ($KUBECONFIG); erst 'unset KUBECONFIG'"; return 1; }
  # the target switches of the gpd and amd scripts (rule 1.6: only inside
  # aks_sam/aks_kc or per command, never in the interactive shell)
  case ${TARGET:-lab} in
    lab) ;;
    *) _aks_err "lab_guard: TARGET ist nicht lab; erst 'unset TARGET'"; return 1 ;;
  esac
  for v in SAM_ENV_FILE SAM_URL SAM_HOME SAM_DNS_NAME SAM_REDIRECT_URI SAM_PLATFORM_TOKEN; do
    if eval "[ -n \"\${$v+x}\" ]"; then
      _aks_err "lab_guard: $v ist gesetzt (nie in der interaktiven Shell); erst 'unset $v'"
      return 1
    fi
  done
  ctx=$(command kubectl config current-context 2>/dev/null) || ctx=""
  [ "$ctx" = rancher-desktop ] ||
    { _aks_err "lab_guard: Kontext ist '${ctx:-?}', nicht rancher-desktop"; return 1; }
  if grep -q aks-eurocis "$HOME/.kube/config" 2>/dev/null; then
    _aks_err "lab_guard: aks-eurocis steht in ~/.kube/config (nie dort; nur $AKS_KUBECONFIG)"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# Azure: tags, Key Vault, ACR pull secret, IP register, stop/start
# ---------------------------------------------------------------------------

aks_tags() {   # mandatory tags of gebit-showcase (fallback .env.aks) -> array TAGS, no output
  local j o d
  TAGS=()
  j=$(az group show -n "$AKS_RG" --query tags -o json) ||
    { _aks_err "aks_tags: az group show -n $AKS_RG fehlgeschlagen (az login?)"; return 1; }
  o=$(printf '%s' "$j" | jq -r 'if type == "object" then (to_entries[]
        | select(.key | ascii_downcase == "owner") | .value) else empty end' 2>/dev/null | head -1)
  d=$(printf '%s' "$j" | jq -r 'if type == "object" then (to_entries[]
        | select(.key | ascii_downcase == "created date") | .value) else empty end' 2>/dev/null | head -1)
  [ -n "$o" ] || o=$(_aks_env OWNER_TAG)
  [ -n "$d" ] || d=$(_aks_env CREATED_DATE)
  [ -n "$o" ] ||
    { _aks_err "aks_tags: Owner fehlt ($AKS_RG ohne Tag, OWNER_TAG in .env.aks leer)"; return 1; }
  printf '%s\n' "$d" | grep -Eqx '[0-9]{2}\.[0-9]{2}\.[0-9]{4}' ||
    { _aks_err "aks_tags: Created Date fehlt oder ist nicht dd.mm.yyyy ($AKS_RG, CREATED_DATE)"; return 1; }
  TAGS=("Owner=$o" "Created Date=$d")
}

kv() {   # kv NAME: secret value without newline on stdout (pipes only)
  local v
  [ $# -eq 1 ] && [ -n "$1" ] || { _aks_err "Aufruf: kv NAME | ..."; return 2; }
  _aks_noxtrace || return 1
  _aks_need_kv || return 1
  [ -t 1 ] && { _aks_err "kv: nur für Pipes, nie auf den Bildschirm"; return 1; }
  v=$(az keyvault secret show --vault-name "$AKS_KV" -n "$1" --query value -o tsv) ||
    { _aks_err "kv: $1 nicht lesbar"; return 1; }
  [ -n "$v" ] || { _aks_err "kv: $1 ist leer"; return 1; }
  printf '%s' "$v"
}

kv_new() (   # kv_new NAME [BYTES]: hex password (default 24 bytes), only if absent
  set -o pipefail
  n=${1:-} b=${2:-24}
  [ -n "$n" ] || { _aks_err "Aufruf: kv_new NAME [BYTES]"; return 2; }
  printf '%s\n' "$b" | grep -Eqx '[0-9]{1,3}' && [ "$b" -ge 8 ] && [ "$b" -le 64 ] ||
    { _aks_err "kv_new: BYTES zwischen 8 und 64"; return 2; }
  _aks_noxtrace || return 1
  _aks_need_kv || return 1
  if e=$(az keyvault secret show --vault-name "$AKS_KV" -n "$n" -o none 2>&1); then
    printf 'kv_new: %s vorhanden\n' "$n"
    return 0
  fi
  case $e in
    *SecretNotFound*) ;;
    *) _aks_err "kv_new: $n nicht prüfbar, nichts angelegt: $e"; return 1 ;;
  esac
  openssl rand -hex "$b" | tr -d '\n' |
    az keyvault secret set --vault-name "$AKS_KV" -n "$n" --file /dev/stdin -o none ||
    { _aks_err "kv_new: $n nicht angelegt"; return 1; }
  printf 'kv_new: %s angelegt\n' "$n"
)

acr_pull() (   # acr_pull NS: namespace + Secret acr-pull (dockerconfigjson) per SSA
  set -o pipefail
  ns=${1:-}
  [ -n "$ns" ] || { _aks_err "Aufruf: acr_pull NAMESPACE"; return 2; }
  _aks_noxtrace || return 1
  aks_guard || return 1
  _aks_need_acr || return 1
  _aks_need_kv || return 1
  tok=$(kv acr-pull-token) || return 1
  kaks create namespace "$ns" --dry-run=client -o yaml | kaks apply -f - || return 1
  printf '%s' "$tok" | jq -Rs --arg r "$AKS_ACR.azurecr.io" --arg ns "$ns" '{
      apiVersion: "v1", kind: "Secret", type: "kubernetes.io/dockerconfigjson",
      metadata: {name: "acr-pull", namespace: $ns},
      data: {".dockerconfigjson": ({auths: {($r): {username: "aks-pull", password: .,
        auth: ("aks-pull:\(.)" | @base64)}}} | tojson | @base64)}}' |
    kaks apply --server-side -f -
)

aks_ips() (   # ingress and egress IP against the register in $AKS_STATE
  set -o pipefail
  set +o noclobber   # the register files are rewritten
  (umask 077; mkdir -p "$AKS_STATE") || return 1
  eid=$(az aks show -g "$AKS_RG" -n "$AKS_NAME" -o tsv \
    --query "networkProfile.loadBalancerProfile.effectiveOutboundIPs[0].id") ||
    { _aks_err "aks_ips: az aks show fehlgeschlagen"; return 1; }
  [ -n "$eid" ] || { _aks_err "aks_ips: keine Egress-IP-Ressource"; return 1; }
  eip=$(az network public-ip show --ids "$eid" --query ipAddress -o tsv) || eip=""
  iip=$(az network public-ip show -g "$AKS_NODE_RG" -n pip-aks-ingress \
    --query ipAddress -o tsv) || iip=""
  for v in "$eip" "$iip"; do
    printf '%s\n' "$v" | grep -Eqx '[0-9]{1,3}(\.[0-9]{1,3}){3}' ||
      { _aks_err "aks_ips: IP nicht lesbar ('$v'), Register unverändert"; return 1; }
  done
  rc=0
  _aks_reg egress-ip "$eip" || rc=1
  _aks_reg ingress-ip "$iip" || rc=1
  return $rc
)

aks_stop() (   # refused 05.-18.02.2027 (AKS_FORCE=1 overrides); writes last-stop
  set +o noclobber   # last-stop is rewritten
  d=$(date +%Y%m%d)
  if [ "${AKS_FORCE:-}" != 1 ] && [ "$d" -ge 20270205 ] && [ "$d" -le 20270218 ]; then
    _aks_err "aks_stop: verweigert 05.-18.02.2027 (24/7 ab Freeze); Notfall: AKS_FORCE=1 aks_stop"
    return 1
  fi
  p=$(_aks_power) || { _aks_err "aks_stop: az aks show fehlgeschlagen (az login?)"; return 1; }
  if [ "$p" = Stopped ]; then
    echo "aks_stop: $AKS_NAME ist bereits Stopped"
    return 0
  fi
  (umask 077; mkdir -p "$AKS_STATE") || return 1
  az aks stop -g "$AKS_RG" -n "$AKS_NAME" -o none
  rc=$?
  # written even after a failed stop: a half-stopped cluster also needs the 30 min
  date +%s > "$AKS_STATE/last-stop"
  printf 'aks_stop: %s, last-stop %s\n' "$(_aks_power)" "$(date '+%d.%m.%Y %H:%M')"
  return $rc
)

aks_start() (   # >= 30 min after the stop; node, aks_ips, awe once after gwe Ready, pods
  set -o pipefail
  sam_ns=sam-solace-lab gwe=agent-mesh-solace-agent-mesh-gwe awe=agent-mesh-solace-agent-mesh-awe
  p=$(_aks_power) || { _aks_err "aks_start: az aks show fehlgeschlagen (az login?)"; return 1; }
  started=0
  if [ "$p" = Running ]; then
    echo "aks_start: $AKS_NAME läuft bereits (kein Start, kein awe-Neustart)"
  else
    last=$(cat "$AKS_STATE/last-stop" 2>/dev/null) || last=""
    printf '%s\n' "$last" | grep -Eqx '[0-9]+' || last=0
    now=$(date +%s)
    if [ $((now - last)) -lt 1800 ]; then
      _aks_err "aks_start: frühestens 30 min nach dem Stopp, noch $(( (1800 - now + last + 59) / 60 )) min"
      return 1
    fi
    t0=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    az aks start -g "$AKS_RG" -n "$AKS_NAME" -o none ||
      { _aks_err "aks_start: az aks start fehlgeschlagen"; return 1; }
    started=1
  fi
  aks_guard || return 1
  i=0
  until [ -n "$(kaks get nodes -o name 2>/dev/null)" ]; do
    i=$((i + 1))
    [ $i -le 60 ] || { _aks_err "aks_start: nach 10 min kein Node registriert"; return 1; }
    sleep 10
  done
  kaks wait --for=condition=Ready node --all --timeout=15m ||
    { _aks_err "aks_start: Node nicht Ready"; return 1; }
  rc=0
  aks_ips || rc=1
  samdep=""
  if [ "$started" = 1 ]; then
    # empty = not installed; an API error must not read as "not installed"
    samdep=$(kaks -n "$sam_ns" get deploy "$gwe" --ignore-not-found -o name) || {
      _aks_err "aks_start: FEHLER Deployment $gwe nicht lesbar, awe nicht neu gestartet"
      rc=1 samdep=error
    }
  fi
  if [ "$samdep" = error ]; then
    :
  elif [ -n "$samdep" ]; then
    # gwe counts as Ready only with a Ready transition after the start: the
    # pod status from before the stop may still read Ready right after it.
    i=0 ready=0
    while [ $i -lt 120 ]; do
      if kaks -n "$sam_ns" get pods -o json \
          -l app.kubernetes.io/instance=agent-mesh,app.kubernetes.io/component=gwe |
        jq -e --arg t0 "$t0" '[.items[].status.conditions[]? | select(.type == "Ready"
          and .status == "True" and .lastTransitionTime >= $t0)] | length > 0' >/dev/null 2>&1; then
        ready=1
        break
      fi
      i=$((i + 1))
      sleep 10
    done
    if [ "$ready" = 1 ]; then
      kaks -n "$sam_ns" rollout restart "deploy/$awe" &&
        kaks -n "$sam_ns" rollout status "deploy/$awe" --timeout=10m || rc=1
    else
      _aks_err "aks_start: gwe nach 20 min nicht Ready, awe nicht neu gestartet"
      rc=1
    fi
  elif [ "$started" = 1 ]; then
    echo "aks_start: SAM nicht installiert, kein awe-Neustart"
  fi
  echo "Pods nicht Running (oder nicht ready):"
  if pods=$(kaks get pods -A --no-headers); then
    printf '%s\n' "$pods" | awk '
      NF == 0 || $4 == "Completed" { next }
      { split($3, r, "/") }
      $4 != "Running" || r[1] != r[2] { print; n++ }
      END { if (!n) print "  keine" }'
  else
    echo "  FEHLER: Pod-Liste nicht lesbar"
    rc=1
  fi
  return $rc
)

# ---------------------------------------------------------------------------
# SAM, Keycloak, broker (subshells with AKS variables only)
# ---------------------------------------------------------------------------

_aks_run() (   # _aks_run sam|kc CMD...: CMD in a subshell against AKS
  set -o pipefail
  mode=$1
  shift
  [ $# -gt 0 ] || { _aks_err "Aufruf: aks_$mode CMD [ARGS]"; return 2; }
  # Lab-only scripts read only the lab .env and act on the current context and
  # on lab endpoints (1.6); in here the context is AKS, so they never run here.
  for a in "$@"; do
    case ${a##*/} in
      start.sh|stop.sh|teardown-keycloak-*.sh|load-images.sh|purge-images.sh|upgrade-preflight.sh)
        _aks_err "aks_$mode: ${a##*/} ist ein Lab-Skript (nur .env, aktueller Kontext), nie gegen AKS (1.6)"
        return 1 ;;
    esac
    case $a in
      desktop/*.sh|*/desktop/*.sh)
        _aks_err "aks_$mode: $a ist ein Lab-Skript (SAM-Desktop), nie gegen AKS (1.6)"
        return 1 ;;
    esac
  done
  _aks_noxtrace || return 1
  aks_guard || return 1
  ctx=$(KUBECONFIG="$AKS_KUBECONFIG" command kubectl config current-context 2>/dev/null) || ctx=""
  [ "$ctx" = "$AKS_CONTEXT" ] ||
    { _aks_err "aks_$mode: current-context in $AKS_KUBECONFIG ist '${ctx:-?}'," \
        "nicht $AKS_CONTEXT"; return 1; }
  [ -f "$AMD/.env.aks" ] ||
    { _aks_err "aks_$mode: $AMD/.env.aks fehlt (amd_env_aks, A15)"; return 1; }
  # The gpd scripts (TARGET=aks) take SAM_HOME and SAM_URL from
  # gebit-price-agent-demo/.env.aks: a login made in here must be the one they
  # look for, so that file must name the same home and URL as this one.
  h=$(_aks_env SAM_HOME) u=$(_aks_env SAM_URL)
  case $h in
    '$HOME'|'$HOME/'*) h=$HOME${h#'$HOME'} ;;
    '${HOME}'|'${HOME}/'*) h=$HOME${h#'${HOME}'} ;;
  esac
  if [ "$h" != "$AKS_SAM_HOME" ] || [ "$u" != "https://$FQDN" ]; then
    _aks_err "aks_$mode: SAM_HOME oder SAM_URL in $GPD/.env.aks weicht von aks.sh ab;" \
      "erwartet SAM_HOME=\$HOME/.config/eurocis-aks/sam und SAM_URL=https://$FQDN"
    return 1
  fi
  (umask 077; mkdir -p "$AKS_SAM_HOME") || return 1
  # no token or secret of the interactive shell reaches the AKS run (the LLM key
  # variable is named in two parts: scripts/check_hygiene.sh forbids the name)
  unset SAM_AUTH_TOKEN SAM_PLATFORM_TOKEN KEYCLOAK_ADMIN_PASSWORD KEYCLOAK_CLIENT_SECRET \
    LLM_SERVICE_""API_KEY GOOGLE_AI_STUDIO_API_KEY
  export KUBECONFIG="$AKS_KUBECONFIG" SAM_ENV_FILE="$AMD/.env.aks" \
    SAM_HOME="$AKS_SAM_HOME" SAM_URL="https://$FQDN" SAM_DNS_NAME="$FQDN" \
    SAM_REDIRECT_URI="https://$FQDN/api/v1/auth/callback"
  if [ "$mode" = kc ]; then
    _aks_kc_pf || return 1
    KEYCLOAK_ADMIN_PASSWORD=$(kv keycloak-admin) || return 1
    export KEYCLOAK_ADMIN_PASSWORD
  fi
  # sam 2.542.1 keeps its OAuth login cache under $HOME/Library/Application
  # Support/sam and ignores SAM_HOME and --sam-home for it: `sam` here always
  # runs with HOME=$AKS_SAM_HOME, so the lab login is never read or overwritten.
  # Same CLI as the AMD scripts: SAM_CLI_PATH of .env.aks wins over PATH.
  _aks_cli=$(sed -n 's/^SAM_CLI_PATH=//p' "$SAM_ENV_FILE" | tail -1 |
    sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/")
  if [ -z "$_aks_cli" ] || [ ! -x "$_aks_cli" ]; then
    _aks_cli=$(command -v sam 2>/dev/null) || _aks_cli=""
    case "$_aks_cli" in /*) ;; *) _aks_cli="" ;; esac
  fi
  sam() {
    [ -n "$_aks_cli" ] || { _aks_err "aks_sam: sam CLI nicht gefunden"; return 127; }
    HOME="$AKS_SAM_HOME" "$_aks_cli" "$@"
  }
  "$@"
)
aks_sam() { _aks_run sam "$@"; }
aks_kc() { _aks_run kc "$@"; }

amd_env_aks() (   # writes agent-mesh-deployment/.env.aks (600) without showing values
  set -o pipefail
  set +o noclobber   # the mktemp file is written over
  umask 077
  _aks_noxtrace || return 1
  git -C "$AMD" check-ignore -q .env.aks ||
    { _aks_err "amd_env_aks: $AMD/.env.aks ist nicht gitignored" \
        "(Zeile .env.aks in agent-mesh-deployment/.gitignore), STOP"; return 1; }
  lab="$AMD/.env"
  [ -f "$lab" ] || { _aks_err "amd_env_aks: Lab-$lab fehlt"; return 1; }
  # the LLM key variable in two parts (scripts/check_hygiene.sh forbids the name)
  for k in LLM_SERVICE_""API_KEY SAM_CHART_PATH SAM_CLI_PATH; do
    grep -Eq "^$k=.+" "$lab" || { _aks_err "amd_env_aks: $k fehlt in der Lab-.env"; return 1; }
  done
  if grep -Eq '^LLM_SERVICE_''API_KEY=("|'"'"')?changeme' "$lab"; then
    _aks_err "amd_env_aks: LLM_SERVICE_""API_KEY in der Lab-.env ist ein Platzhalter"
    return 1
  fi
  mkdir -p "$AKS_STATE" || return 1
  tmp=$(mktemp "$AKS_STATE/amd-env-aks.XXXXXX") || return 1
  # the temp file holds the LLM key: gone on every way out of this subshell
  # (after the mv the rm is a no-op)
  trap 'rm -f "$tmp"' EXIT
  trap 'exit 1' HUP INT TERM
  {
    echo "# agent-mesh-deployment/.env.aks: AKS values of the amd scripts (aks_sam, aks_kc,"
    echo "# sam_helm). Written by amd_env_aks (aks.sh); git-ignored, mode 600, never commit."
    echo "KEYCLOAK_URL=http://127.0.0.1:18081/auth"
    echo "KEYCLOAK_REALM=solace-lab"
    echo "KEYCLOAK_ADMIN_USER=admin"
    echo "KEYCLOAK_CLIENT_ID=solace-agent-mesh"
    echo "KEYCLOAK_ISSUER=https://$FQDN/auth/realms/solace-lab"
    # keep the client secret of setup-keycloak-client.sh across a rewrite
    [ -f "$AMD/.env.aks" ] && grep '^KEYCLOAK_CLIENT_SECRET=' "$AMD/.env.aks" | tail -1
    for k in LLM_SERVICE_""API_KEY SAM_CHART_PATH SAM_CLI_PATH; do
      grep "^$k=" "$lab" | tail -1
    done
  } > "$tmp" || { rm -f "$tmp"; return 1; }
  chmod 600 "$tmp" && mv -f "$tmp" "$AMD/.env.aks" || { rm -f "$tmp"; return 1; }
  echo "amd_env_aks: $AMD/.env.aks geschrieben (Modus 600; LLM-Key, Chart- und CLI-Pfad" \
    "aus der Lab-.env, nicht angezeigt)"
)

kc_token() (   # admin token of the master realm via 18081 on stdout (pipes only; 60 s)
  set -o pipefail
  _aks_noxtrace || return 1
  [ -t 1 ] && { _aks_err "kc_token: nur für Pipes, nie auf den Bildschirm"; return 1; }
  _aks_kc_pf || return 1
  pw=$(kv keycloak-admin) || return 1
  tok=$(printf '%s' "$pw" | curl -s --max-time 15 --data-urlencode 'password@-' \
    -d grant_type=password -d client_id=admin-cli -d username=admin \
    "$AKS_KC_URL/realms/master/protocol/openid-connect/token" |
    jq -r '.access_token // empty' 2>/dev/null) || tok=""
  [ -n "$tok" ] || { _aks_err "kc_token: kein Admin-Token (Passwort keycloak-admin?)"; return 1; }
  printf '%s' "$tok"
)

kc_set_passwords() (   # passwords of the 7 realm users from kc-user-*; exit 0 only on 7x 204
  set -o pipefail
  _aks_noxtrace || return 1
  _aks_kc_pf || return 1
  ok=0
  for u in sam_admin sam_user sam_manager power_user data_engineer viewer marktleitung; do
    tok=$(kc_token) || { printf '%s FEHLER (Token)\n' "$u"; continue; }
    id=$(_aks_kc_userid "$tok" "$u")
    [ -n "$id" ] || { printf '%s FEHLER (User fehlt im Realm)\n' "$u"; continue; }
    pw=$(kv "kc-user-${u//_/-}") || { printf '%s FEHLER (Key Vault)\n' "$u"; continue; }
    code=$(printf '%s' "$pw" | jq -cRs '{type: "password", value: ., temporary: false}' |
      curl -s -o /dev/null -w '%{http_code}' --max-time 15 -X PUT \
        -H 'Content-Type: application/json' \
        --config <(printf 'header = "Authorization: Bearer %s"\n' "$(_aks_cq "$tok")") \
        --data-binary @- "$AKS_KC_URL/admin/realms/solace-lab/users/$id/reset-password") || code=000
    printf '%s %s\n' "$u" "$code"
    [ "$code" = 204 ] && ok=$((ok + 1))
  done
  [ "$ok" -eq 7 ] || { _aks_err "kc_set_passwords: $ok von 7 gesetzt"; return 1; }
  return 0
)

kc_unlock() (   # kc_unlock USER: lift the brute-force lock of one realm user
  set -o pipefail
  u=${1:-}
  [ -n "$u" ] || { _aks_err "Aufruf: kc_unlock USER"; return 2; }
  _aks_noxtrace || return 1
  _aks_kc_pf || return 1
  tok=$(kc_token) || return 1
  id=$(_aks_kc_userid "$tok" "$u")
  [ -n "$id" ] || { printf '%s FEHLER (User fehlt im Realm)\n' "$u"; return 1; }
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -X DELETE \
    --config <(printf 'header = "Authorization: Bearer %s"\n' "$(_aks_cq "$tok")") \
    "$AKS_KC_URL/admin/realms/solace-lab/attack-detection/brute-force/users/$id") || code=000
  printf '%s %s\n' "$u" "$code"
  [ "$code" = 204 ]
)

kc_bruteforce_off() (   # realm solace-lab without brute-force lockout (owner 23.11.2026)
  # The booth logins are public in the repo: with the lockout anyone could block
  # them by failing five times. Partial realm PUT; token only in a curl config.
  set -o pipefail
  _aks_noxtrace || return 1
  _aks_kc_pf || return 1
  tok=$(kc_token) || return 1
  code=$(printf '%s' '{"bruteForceProtected": false}' |
    curl -s -o /dev/null -w '%{http_code}' --max-time 15 -X PUT \
      -H 'Content-Type: application/json' \
      --config <(printf 'header = "Authorization: Bearer %s"\n' "$(_aks_cq "$tok")") \
      --data-binary @- "$AKS_KC_URL/admin/realms/solace-lab") || code=000
  [ "$code" = 204 ] || { _aks_err "kc_bruteforce_off: PUT HTTP $code"; return 1; }
  now=$(curl -s --max-time 15 \
    --config <(printf 'header = "Authorization: Bearer %s"\n' "$(_aks_cq "$tok")") \
    "$AKS_KC_URL/admin/realms/solace-lab" | jq -r '.bruteForceProtected') || now=""
  printf 'kc_bruteforce_off: solace-lab bruteForceProtected=%s\n' "${now:-?}"
  [ "$now" = false ]
)

semp() (   # semp PATH: SEMP GET over the port-forward 18080 (admin from solace-admin)
  set -o pipefail
  case ${1:-} in
    /SEMP/*) ;;
    *) _aks_err "Aufruf: semp /SEMP/v2/..."; return 2 ;;
  esac
  _aks_noxtrace || return 1
  pw=$(kv solace-admin) || return 1
  curl -sS --max-time 20 --fail-with-body \
    --config <(printf 'user = "admin:%s"\n' "$(_aks_cq "$pw")") "$AKS_SEMP_URL$1"
)

tfa() (   # tfa ARGS: terraform -chdir=$AKS_DIR/broker with TF_VAR_* from the vault
  set -o pipefail
  # terraform.tfstate(.backup) hold the client passwords in plaintext: owner only
  umask 077
  _aks_noxtrace || return 1
  command -v terraform >/dev/null 2>&1 || { _aks_err "tfa: terraform fehlt"; return 1; }
  [ -f "$AKS_DIR/broker/main.tf" ] || { _aks_err "tfa: $AKS_DIR/broker/main.tf fehlt"; return 1; }
  # Never on screen or into another file: -json (show and output print every
  # value), state pull and console (the whole state), -out (a plan file holds
  # the TF_VAR_* values and is not gitignored everywhere).
  case "${1:-} ${2:-}" in
    console\ *|"state pull")
      _aks_err "tfa: nie '$1${2:+ $2}' (zeigt die Passwörter im Klartext)"
      return 2 ;;
  esac
  for a in "$@"; do
    case $a in
      -json|-json=*|--json|--json=*|-out|-out=*|--out|--out=*)
        _aks_err "tfa: nie $a (zeigt oder speichert die Passwörter im Klartext)"
        return 2 ;;
    esac
  done
  for f in terraform.tfstate terraform.tfstate.backup errored.tfstate; do
    if [ -f "$AKS_DIR/broker/$f" ]; then chmod 600 "$AKS_DIR/broker/$f" || return 1; fi
  done
  case ${1:-} in
    ""|init|fmt|validate|version|providers|show|output|state|graph|workspace|-help|--help|-version|--version)
      ;;
    *)
      vpns=$(semp '/SEMP/v2/config/msgVpns?select=msgVpnName&count=100' |
        jq -r '.data[].msgVpnName') ||
        { _aks_err "tfa: SEMP auf 127.0.0.1:18080 nicht erreichbar (Port-Forward aus A13 offen?)"; return 1; }
      if printf '%s\n' "$vpns" | grep -qx amartens-test; then
        _aks_err "tfa: VPN amartens-test auf 127.0.0.1:18080: das ist der Lab-Broker, STOP"
        return 1
      fi
      # no terraform/provider log next to the TF_VAR_* secrets
      [ -z "${TF_LOG:-}${TF_LOG_CORE:-}${TF_LOG_PROVIDER:-}${TF_LOG_PATH:-}" ] ||
        _aks_err "tfa: TF_LOG* ignoriert (Logs könnten Secrets enthalten)"
      unset TF_LOG TF_LOG_CORE TF_LOG_PROVIDER TF_LOG_PATH
      TF_VAR_semp_password=$(kv solace-admin) &&
        TF_VAR_sam_password=$(kv solace-sam) &&
        TF_VAR_gpos_password=$(kv solace-gpos) &&
        TF_VAR_default_password=$(kv solace-default-off) || return 1
      export TF_VAR_semp_password TF_VAR_sam_password TF_VAR_gpos_password TF_VAR_default_password
      ;;
  esac
  terraform -chdir="$AKS_DIR/broker" "$@"
)

sam_helm() (   # haks upgrade --install agent-mesh; secrets and ACR registries via stdin
  set -o pipefail
  _aks_noxtrace || return 1
  # Helm must never print the values document or the rendered Secrets: debug
  # output (--debug, HELM_DEBUG) and -o json/yaml show USER-SUPPLIED/COMPUTED
  # VALUES or the release config in plaintext, and every dry run prints the
  # hook manifests in full: --hide-secret filters only the regular Secrets, not
  # the hooks, and the pre-install hook Secret sam-doctor carries the LLM key and
  # the broker password (checked with helm v4.2.3 and chart 2.3.10).
  for a in "$@"; do
    case $a in
      --reuse-values*|--reset-then-reuse-values*)
        _aks_err "sam_helm: nie --reuse-values (PG-Passwort und Secrets kommen immer neu)"
        return 2 ;;
      --debug|--debug=*)
        _aks_err "sam_helm: nie --debug (zeigt alle Values samt Secrets im Klartext)"
        return 2 ;;
      -o|-o*|--output|--output=*)
        _aks_err "sam_helm: nie -o/--output (json/yaml enthält die Values samt Secrets)"
        return 2 ;;
      --dry-run|--dry-run=*)
        _aks_err "sam_helm: nie --dry-run (zeigt den Hook sam-doctor samt LLM-Key und" \
          "Broker-Passwort, auch mit --hide-secret)"
        return 2 ;;
    esac
  done
  [ -z "${HELM_DEBUG:-}" ] ||
    _aks_err "sam_helm: HELM_DEBUG ignoriert (Debug-Ausgabe zeigt die Secrets)"
  unset HELM_DEBUG
  aks_guard || return 1
  _aks_need_acr || return 1
  _aks_need_kv || return 1
  for f in "$AMD/.env.aks" "$AMD/local-k8s-values.yaml" "$AMD/aks-values.yaml"; do
    [ -f "$f" ] || { _aks_err "sam_helm: $f fehlt"; return 1; }
  done
  # every value comes from .env.aks or the vault, never from the operator shell
  # (a lab KEYCLOAK_CLIENT_SECRET there would otherwise fill a missing line)
  # (the LLM key variable is named in two parts: scripts/check_hygiene.sh forbids
  # the name; eval reads it after the .env.aks below)
  unset KEYCLOAK_CLIENT_SECRET KEYCLOAK_CLIENT_ID KEYCLOAK_ISSUER LLM_SERVICE_""API_KEY \
    SAM_CHART_PATH SAM_CLI_PATH
  # shellcheck source=/dev/null
  . "$AMD/.env.aks" || return 1
  eval 'llm=${LLM_SERVICE_''API_KEY:-}'
  _aks_req sam_helm SAM_CHART_PATH "${SAM_CHART_PATH:-}" &&
    _aks_req sam_helm KEYCLOAK_CLIENT_ID "${KEYCLOAK_CLIENT_ID:-}" &&
    _aks_req sam_helm "KEYCLOAK_CLIENT_SECRET (aks_kc setup-keycloak-client.sh, A15)" \
      "${KEYCLOAK_CLIENT_SECRET:-}" &&
    _aks_req sam_helm "LLM_SERVICE_""API_KEY" "$llm" || return 1
  [ -f "$SAM_CHART_PATH/Chart.yaml" ] ||
    { _aks_err "sam_helm: SAM_CHART_PATH ohne Chart.yaml"; return 1; }
  [ "${KEYCLOAK_ISSUER:-}" = "https://$FQDN/auth/realms/solace-lab" ] ||
    { _aks_err "sam_helm: KEYCLOAK_ISSUER in $AMD/.env.aks ist nicht der AKS-Issuer"; return 1; }
  bpw=$(kv solace-sam) && ssk=$(kv sam-session-secret) && pgpw=$(kv sam-pg-admin) ||
    return 1
  reg="$AKS_ACR.azurecr.io"
  # One JSON values document, read by helm from stdin (-f -) after the two
  # values files, so it wins like --set; no secret is in the argv of helm.
  # Keys checked against chart 2.3.10 (helm template, persistence-layer 1.13.0).
  doc=$(
    printf '{"sam":{"oauthProvider":{"oidc":{"issuer":"%s","clientId":"%s","clientSecret":"%s"}},' \
      "$(_aks_js "$KEYCLOAK_ISSUER")" "$(_aks_js "$KEYCLOAK_CLIENT_ID")" \
      "$(_aks_js "$KEYCLOAK_CLIENT_SECRET")"
    printf '"sessionSecretKey":"%s"},' "$(_aks_js "$ssk")"
    printf '"llmService":{"llmServiceApiKey":"%s"},' "$(_aks_js "$llm")"
    printf '"broker":{"password":"%s"},' "$(_aks_js "$bpw")"
    printf '"samDeployment":{"gwe":{"image":{"registry":"%s"}},' "$reg"
    printf '"str":{"image":{"registry":"%s"}},"s3Init":{"image":{"registry":"%s"}},' "$reg" "$reg"
    printf '"dbInit":{"image":{"registry":"%s"}}},' "$reg"
    printf '"persistence-layer":{"postgresql":{"password":"%s","image":{"registry":"%s"}},' \
      "$(_aks_js "$pgpw")" "$reg"
    printf '"seaweedfs":{"image":{"registry":"%s"}}}}\n' "$reg"
  ) || return 1
  printf '%s\n' "$doc" | haks upgrade --install agent-mesh "$SAM_CHART_PATH" \
    -n sam-solace-lab -f "$AMD/local-k8s-values.yaml" -f "$AMD/aks-values.yaml" -f - "$@"
)

# ---------------------------------------------------------------------------
# TLS: backup to / restore from the Key Vault, SAM copy, ZeroSSL fallback
# ---------------------------------------------------------------------------

_aks_notafter() {   # Secret JSON on stdin -> "notAfter=..." of tls.crt
  jq -r '.data["tls.crt"] // empty' | openssl base64 -d -A 2>/dev/null |
    openssl x509 -noout -enddate 2>/dev/null
}

tls_backup() (   # Secret traefik/ingress-tls -> Key Vault tls-traefik-ingress-tls, verified
  set -o pipefail
  _aks_noxtrace || return 1
  aks_guard || return 1
  _aks_need_kv || return 1
  sec=$(kaks -n traefik get secret ingress-tls -o json) ||
    { _aks_err "tls_backup: Secret traefik/ingress-tls nicht lesbar"; return 1; }
  js=$(printf '%s' "$sec" | jq -c 'del(.metadata.uid, .metadata.resourceVersion,
      .metadata.managedFields, .metadata.creationTimestamp, .metadata.generation,
      .metadata.selfLink, .metadata.ownerReferences,
      .metadata.annotations["kubectl.kubernetes.io/last-applied-configuration"])') ||
    return 1
  printf '%s' "$js" | jq -e '.kind == "Secret" and (.data["tls.crt"] // "") != ""
      and (.data["tls.key"] // "") != ""' >/dev/null ||
    { _aks_err "tls_backup: Secret ohne tls.crt/tls.key, nichts gesichert"; return 1; }
  [ "${#js}" -lt 25000 ] ||
    { _aks_err "tls_backup: Secret größer als 25 KB (Key-Vault-Grenze)"; return 1; }
  printf '%s' "$js" | az keyvault secret set --vault-name "$AKS_KV" \
    -n tls-traefik-ingress-tls --file /dev/stdin -o none ||
    { _aks_err "tls_backup: Ablage im Key Vault fehlgeschlagen"; return 1; }
  back=$(kv tls-traefik-ingress-tls) || return 1
  a=$(printf '%s' "$js" | jq -cS '.data') || a=""
  b=$(printf '%s' "$back" | jq -cS '.data' 2>/dev/null) || b=""
  [ -n "$a" ] && [ "$a" = "$b" ] ||
    { _aks_err "tls_backup: FEHLER Backup im Key Vault weicht vom Cluster ab"; return 1; }
  na=$(printf '%s' "$back" | _aks_notafter) && [ -n "$na" ] ||
    { _aks_err "tls_backup: tls.crt im Backup nicht lesbar"; return 1; }
  printf 'tls_backup: tls-traefik-ingress-tls geprüft (gleich Cluster), %s\n' "$na"
)

tls_restore() (   # Key Vault backup -> Secret traefik/ingress-tls (kaks create)
  set -o pipefail
  _aks_noxtrace || return 1
  aks_guard || return 1
  _aks_need_kv || return 1
  # Only while the Certificate is absent: cert-manager reacts to a missing
  # Secret at once (Issuing=True) and nothing cancels that issuance, so the new
  # certificate would overwrite the restored Secret and cost an issuance.
  crt=$(kaks -n traefik get certificates.cert-manager.io ingress-tls \
    --ignore-not-found -o name) ||
    { _aks_err "tls_restore: Certificate traefik/ingress-tls nicht prüfbar (cert-manager aus A10?)"; return 1; }
  if [ -n "$crt" ]; then
    _aks_err "tls_restore: Certificate traefik/ingress-tls existiert, cert-manager bestellt sonst neu." \
      "Reihenfolge (A11): kaks -n traefik delete certificate ingress-tls &&" \
      "kaks -n traefik delete secret ingress-tls --ignore-not-found && tls_restore &&" \
      "kaks apply -f \"\$AKS_DIR/tls/certificate.yaml\""
    return 1
  fi
  back=$(kv tls-traefik-ingress-tls) || return 1
  printf '%s' "$back" | jq -e '.kind == "Secret" and .metadata.name == "ingress-tls"
      and .metadata.namespace == "traefik" and (.data["tls.crt"] // "") != ""' >/dev/null ||
    { _aks_err "tls_restore: Backup ist kein Secret traefik/ingress-tls"; return 1; }
  printf '%s' "$back" | kaks create -f - || return 1
  printf 'tls_restore: traefik/ingress-tls aus dem Key Vault, %s\n' \
    "$(printf '%s' "$back" | _aks_notafter)"
)

sam_tls_copy() (   # fallback of A16 only: type and data of ingress-tls as sam-solace-lab/sam-tls
  set -o pipefail
  _aks_noxtrace || return 1
  aks_guard || return 1
  sec=$(kaks -n traefik get secret ingress-tls -o json) ||
    { _aks_err "sam_tls_copy: Secret traefik/ingress-tls nicht lesbar"; return 1; }
  printf '%s' "$sec" | jq -e '(.data["tls.crt"] // "") != ""' >/dev/null ||
    { _aks_err "sam_tls_copy: Secret ohne tls.crt"; return 1; }
  printf '%s' "$sec" | jq '{apiVersion: "v1", kind: "Secret", type: .type, data: .data,
      metadata: {name: "sam-tls", namespace: "sam-solace-lab"}}' |
    kaks apply --server-side -f -
)

zerossl_on() (   # ZeroSSL fallback (4.3): EAB secret, issuer, certificate, tls_backup
  set -o pipefail
  _aks_noxtrace || return 1
  aks_guard || return 1
  tpl="$AKS_DIR/tls/zerossl-issuer.tpl.yaml"
  [ -f "$tpl" ] && grep -q '__EAB_KID__' "$tpl" && grep -q 'name: zerossl-eab' "$tpl" &&
    grep -q 'key: secret' "$tpl" ||
    { _aks_err "zerossl_on: $tpl fehlt oder ohne Platzhalter/zerossl-eab/key secret"; return 1; }
  kid=$(_aks_env ACME_EAB_KID) hmac=$(_aks_env ACME_EAB_HMAC)
  _aks_req zerossl_on "ACME_EAB_KID in gebit-price-agent-demo/.env.aks" "$kid" &&
    _aks_req zerossl_on "ACME_EAB_HMAC in gebit-price-agent-demo/.env.aks" "$hmac" || return 1
  printf '%s\n' "$kid" | grep -Eqx '[A-Za-z0-9_-]+' ||
    { _aks_err "zerossl_on: ACME_EAB_KID mit unerwarteten Zeichen"; return 1; }
  kaks get namespace cert-manager -o name >/dev/null ||
    { _aks_err "zerossl_on: Namespace cert-manager fehlt (A10)"; return 1; }
  printf '%s' "$hmac" | kaks -n cert-manager create secret generic zerossl-eab \
    --from-file=secret=/dev/stdin --dry-run=client -o yaml |
    kaks apply --server-side -f - || return 1
  sed "s/__EAB_KID__/$kid/g" "$tpl" | kaks apply -f - || return 1
  kaks wait clusterissuer/zerossl --for=condition=Ready --timeout=5m ||
    { _aks_err "zerossl_on: ClusterIssuer zerossl nicht Ready (EAB-Daten?)"; return 1; }
  kaks -n traefik patch certificate ingress-tls --type merge -p \
    '{"spec":{"issuerRef":{"group":"cert-manager.io","kind":"ClusterIssuer","name":"zerossl"}}}' ||
    return 1
  i=0
  until [ "$(kaks -n traefik get secret ingress-tls \
      -o jsonpath='{.metadata.annotations.cert-manager\.io/issuer-name}' 2>/dev/null)" = zerossl ]; do
    i=$((i + 1))
    [ $i -le 90 ] || { _aks_err "zerossl_on: nach 15 min kein Zertifikat von zerossl"; return 1; }
    sleep 10
  done
  kaks -n traefik wait certificate/ingress-tls --for=condition=Ready --timeout=15m || return 1
  echo "zerossl_on: ingress-tls kommt von zerossl; tls/certificate.yaml auf Issuer zerossl umstellen (4.3)"
  tls_backup
)

# ---------------------------------------------------------------------------
# network checks
# ---------------------------------------------------------------------------

net_check() (   # closed ports on the ingress IP; HTTPS RTT p50/p95 over one connection
  set -o pipefail
  ip=$(cat "$AKS_STATE/ingress-ip" 2>/dev/null) || ip=""
  [ -n "$ip" ] || ip=$(dig +short "$FQDN" 2>/dev/null | tail -1)
  printf '%s\n' "$ip" | grep -Eqx '[0-9]{1,3}(\.[0-9]{1,3}){3}' ||
    { _aks_err "net_check: keine Ingress-IP (aks_ips oder dig $FQDN)"; return 1; }
  rc=0 np=""
  if aks_guard; then
    np=$(kaks -n traefik get svc traefik \
      -o jsonpath='{.spec.ports[*].nodePort} {.spec.healthCheckNodePort}') ||
      { _aks_err "net_check: FEHLER Traefik-NodePorts nicht lesbar"; rc=1; }
  else
    _aks_err "net_check: FEHLER NodePorts ungeprüft"
    rc=1
  fi
  for p in $(printf '%s ' 8080 9000 8008 55555 $np); do
    if nc -z -G 3 -w 3 "$ip" "$p" >/dev/null 2>&1; then
      printf '%s:%s OFFEN\n' "$ip" "$p"
      rc=1
    else
      printf '%s:%s zu\n' "$ip" "$p"
    fi
  done
  res=$(i=0
    while [ $i -lt 200 ]; do
      printf 'url = "https://%s/api/state"\noutput = "/dev/null"\n' "$FQDN"
      i=$((i + 1))
    done | curl -s --max-time 10 --config - -w '%{http_code} %{time_total} %{num_connects}\n')
  ok=$(printf '%s\n' "$res" | awk '$1 == 200 { n++ } END { print n + 0 }')
  conns=$(printf '%s\n' "$res" | awk '{ s += $3 } END { print s + 0 }')
  pct=$(printf '%s\n' "$res" | awk '$1 == 200 { print $2 * 1000 }' | sort -n | awk '
    { a[NR] = $1 }
    END {
      if (!NR) { print "p50 - ms, p95 - ms"; exit }
      i = int((NR * 50 + 99) / 100); j = int((NR * 95 + 99) / 100)
      printf "p50 %.0f ms, p95 %.0f ms\n", a[i], a[j]
    }')
  printf 'HTTPS https://%s/api/state: %s von 200 mit 200, %s Verbindung(en), %s\n' \
    "$FQDN" "$ok" "$conns" "$pct"
  [ "$ok" = 200 ] || rc=1
  return $rc
)

sam_netpol_check() (   # from gpos-ui: every port of SAM's Postgres and SeaweedFS must be "zu"
  set -o pipefail
  aks_guard || return 1
  ns=sam-solace-lab
  svcs=$(kaks -n "$ns" get svc -o json) ||
    { _aks_err "sam_netpol_check: Services in $ns nicht lesbar"; return 1; }
  sel='.items[] | select(.metadata.name | test("postgresql|seaweedfs"))'
  # Service ports by service DNS name, then every container port of the backing
  # pods by pod IP; SeaweedFS also the default listeners of "weed server -s3"
  # (4.48) that its Service does not list: volume 8080/18080, filer
  # 8888/18888, master gRPC 19333, S3 gRPC 18333, Iceberg REST 8181, Lance 9101.
  list=$(printf '%s' "$svcs" | jq -r --arg ns "$ns" "$sel"' | .metadata.name as $n
    | .spec.ports[] | "\($n):\(.port)=\($n).\($ns).svc.cluster.local:\(.port)"') || list=""
  [ -n "$list" ] ||
    { _aks_err "sam_netpol_check: keine Services *postgresql*/*seaweedfs* in $ns"; return 1; }
  sels=$(printf '%s' "$svcs" | jq -r "$sel"' | select(.spec.selector != null)
    | "\(.metadata.name) \(.spec.selector | to_entries | map("\(.key)=\(.value)") | join(","))"')
  while read -r svc lbl; do
    [ -n "$lbl" ] || continue
    extra='[]'
    case $svc in
      *seaweedfs*) extra='[8080,18080,8888,18888,9333,19333,8333,18333,8181,9101]' ;;
    esac
    pods=$(kaks -n "$ns" get pods -l "$lbl" -o json) ||
      { _aks_err "sam_netpol_check: Pods von $svc nicht lesbar"; return 1; }
    list="$list
$(printf '%s' "$pods" | jq -r --argjson extra "$extra" '.items[]
      | select(.status.podIP != null) | .metadata.name as $p | .status.podIP as $ip
      | ([.spec.containers[].ports[]?.containerPort] + $extra | unique)[]
      | "\($p):\(.)=\($ip):\(.)"')"
  done <<EOF
$sels
EOF
  set --
  while IFS= read -r t; do
    [ -n "$t" ] && set -- "$@" "$t"
  done <<EOF
$list
EOF
  py='
import socket, sys
rc = 0
for t in sys.argv[1:]:
    label, _, target = t.partition("=")
    host, _, port = target.rpartition(":")
    try:
        socket.create_connection((host, int(port)), timeout=3).close()
        state, rc = "OFFEN", 1
    except socket.gaierror:
        state, rc = "FEHLER (DNS)", 1
    except socket.timeout:
        state = "zu (timeout)"
    except OSError as e:
        state = "zu (%s)" % (e.strerror or type(e).__name__)
    print(label, state, flush=True)
sys.exit(rc)
'
  out=$(kaks -n gpos-demo exec deploy/gpos-ui -c ui -- python -c "$py" "$@")
  rc=$?
  printf '%s\n' "$out"
  case $out in *OFFEN*) rc=1 ;; esac
  [ -n "$out" ] || { _aks_err "sam_netpol_check: keine Ausgabe aus gpos-demo/deploy/gpos-ui"; rc=1; }
  return $rc
)

aks_myip() (   # own public IP as Traefik sees it: one probe request, read from its access log
  # (no third-party service). Inside $( ... ) every tool is called via "command":
  # that text is parsed at run time, when the operator's aliases are active again.
  set -o pipefail
  aks_guard || return 1
  tag="aks-myip-$(command od -An -N6 -tx1 /dev/urandom | command tr -d ' \n')"
  command curl -q -s -o /dev/null --max-time 10 "https://$FQDN/$tag" ||
    { _aks_err "aks_myip: keine Antwort von https://$FQDN"; return 1; }
  i=0 ip=""
  while [ -z "$ip" ] && [ $i -lt 10 ]; do
    sleep 1
    i=$((i + 1))
    ip=$(kaks -n traefik logs deploy/traefik --since=2m 2>/dev/null |
      command grep -F "\"RequestPath\":\"/$tag\"" | command tail -1 |
      command sed -n 's/.*"ClientHost":"\([^"]*\)".*/\1/p')
  done
  [ -n "$ip" ] || { _aks_err "aks_myip: Probe nicht im Access-Log von Traefik"; return 1; }
  printf '%s\n' "$ip"
)

grafana_off() (   # remove the Grafana route and its allowlist: /grafana/ closed for everyone
  aks_guard || return 1
  kaks -n monitoring delete ingressroute grafana --ignore-not-found &&
    kaks -n monitoring delete middleware grafana-allow --ignore-not-found || return 1
  echo "grafana_off: Route und Allowlist entfernt, Grafana nur per Port-Forward"
)

grafana_allow() (   # grafana_allow [CIDR...]: /grafana/ only for own IP + GRAFANA_ALLOW + CIDRs
  # Replaces the whole allowlist (an old home or office IP drops out), applies
  # the IngressRoute and proves both sides: 200 from here, 403 from inside the
  # cluster. Any other cluster answer removes the route again (fail closed).
  # Never from the booth network or 5G (shared NAT/CGNAT IP, runbook A11).
  # The IPs never reach argv or a file; they are shown only on a terminal.
  set -o pipefail
  aks_guard || return 1
  tpl="$AKS_DIR/grafana/route.tpl.yaml"
  [ -f "$tpl" ] && command grep -q '__GRAFANA_ALLOW__' "$tpl" ||
    { _aks_err "grafana_allow: $tpl fehlt oder ohne Platzhalter"; return 1; }
  kaks -n monitoring get svc kube-prometheus-grafana -o name >/dev/null ||
    { _aks_err "grafana_allow: Service monitoring/kube-prometheus-grafana fehlt (A8)"; return 1; }
  me=$(aks_myip) || return 1
  # stdin: one network per word (commas and blanks separate); only public
  # networks, IPv4 at least /16, IPv6 at least /48, no zone id, duplicates
  # dropped. stdout: "# N" and the template with the JSON-quoted list.
  doc=$( { printf '%s\n' "$me" "$(_aks_env GRAFANA_ALLOW)"; printf '%s\n' "$@"; } |
    command python3 -c '
import ipaddress, json, re, sys
out = []
for raw in re.split(r"[\s,]+", sys.stdin.read().strip()):
    if not raw:
        continue
    if not re.fullmatch(r"[0-9A-Fa-f:.]+(/[0-9]{1,3})?", raw):
        sys.exit("grafana_allow: keine IP/kein CIDR: " + raw)
    try:
        net = ipaddress.ip_network(raw, strict=False)
    except ValueError:
        sys.exit("grafana_allow: keine IP/kein CIDR: " + raw)
    if not net.is_global or net.prefixlen < (16 if net.version == 4 else 48):
        sys.exit("grafana_allow: nicht öffentlich oder zu weit: " + str(net))
    if str(net) not in out:
        out.append(str(net))
if not out:
    sys.exit("grafana_allow: leere Allowlist")
tpl = open(sys.argv[1], encoding="utf-8").read()
print("# %d" % len(out))
sys.stdout.write(tpl.replace("__GRAFANA_ALLOW__", ", ".join(json.dumps(n) for n in out)))
' "$tpl") || return 1
  n=$(printf '%s\n' "$doc" | command sed -n '1s/^# //p')
  printf '%s\n' "$doc" | kaks apply -f - || return 1
  if [ -t 1 ]; then
    printf 'grafana_allow: https://%s/grafana/ nur für %s\n' "$FQDN" \
      "$(printf '%s\n' "$doc" | command sed -n 's/^ *sourceRange: \[\(.*\)\]$/\1/p')"
  else
    printf 'grafana_allow: https://%s/grafana/ nur für %s Netz(e)\n' "$FQDN" "$n"
  fi
  # Traefik picks the new route up within seconds; then both sides of the rule
  i=0 own="" inside=""
  while [ $i -lt 12 ]; do
    sleep 5
    i=$((i + 1))
    own=$(command curl -q -s -o /dev/null -w '%{http_code}' --max-time 10 \
      "https://$FQDN/grafana/api/health")
    [ "$own" = 200 ] && break
  done
  pod="grafana-probe-$(command od -An -N4 -tx1 /dev/urandom | command tr -d ' \n')"
  out=$(kaks -n default run "$pod" --rm -i --quiet --restart=Never \
    --image="$CURL_IMG" -- curl -s -o /dev/null -w '%{http_code}\n' --max-time 10 \
    "https://$FQDN/grafana/api/health" 2>&1)
  inside=$(printf '%s\n' "$out" | command tr -d '\r' | command grep -E '^[0-9]{3}$' |
    command tail -1)
  printf 'grafana_allow: eigene IP %s (Soll 200), aus dem Cluster %s (Soll 403)\n' \
    "${own:-000}" "${inside:-000}"
  if [ "$inside" != 403 ]; then
    [ -n "$inside" ] || printf '%s\n' "$out" | command tail -3 >&2
    _aks_err "grafana_allow: Sperre nicht belegt, Route wird entfernt"
    grafana_off
    return 1
  fi
  [ "$own" = 200 ] ||
    { _aks_err "grafana_allow: eigene IP bekommt $own (Allowlist greift, Route bleibt)"; return 1; }
)

# restore the operator's alias expansion (switched off at the top)
if [ "$_aks_al" = 1 ]; then
  if [ -n "${ZSH_VERSION:-}" ]; then setopt aliases; else shopt -s expand_aliases; fi
fi
unset _aks_al
