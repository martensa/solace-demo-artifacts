#!/bin/bash
# aks-check.sh -- read-only checks of the public AKS name (AKS-MIGRATION-PLAN 1.4,
# A18, G2a, 4.4): one line OK or FEHLER per check, exit 0 only if every check is OK.
#   scripts/aks-check.sh [FQDN]     default: the showcase name below
# Needs curl, openssl and grpcurl; no kubeconfig, no .env.aks, no secret, no login.
# Grafana (/grafana/) is open only for the IP allowlist of grafana_allow: by default the
# caller counts as outside it (Grafana must not answer); from an allowlisted IP run
# AKS_CHECK_GRAFANA=frei scripts/aks-check.sh, then Grafana must answer.
# Read-only: GET requests, /kasse and /api/state for the test till 99 (the booth till
# stays untouched), the gRPC routes probed with a method no service has (the server
# answers UNIMPLEMENTED, no RPC runs). At most one request per rate-limited path;
# /api/pos/ and /api/demo/ are never called.
# A path without a route lands at SAM, which answers 200 for almost anything: the
# "zu" checks therefore look at the content, not at the status code; a Basic/Digest
# login challenge counts as open too (a target behind an auth wall is still routed).
# Written for /bin/bash 3.2 (macOS): no mapfile, no associative arrays; curl gets -q.
set -uo pipefail

FQDN_DEFAULT=eurocis-showcase.germanywestcentral.cloudapp.azure.com
TILL=99
PURCHASE=de.gebit.rp.purchase.purchase.v2.service.PurchaseTransactionService
WWS=de.showcase.wws.v1.service.MerchandiseService
LOYALTY=de.showcase.loyalty.v1.service.LoyaltyService
CERT_MIN_DAYS=14

case "${1:-}" in
  -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
esac
GRAFANA_MODE="${AKS_CHECK_GRAFANA:-zu}"
case "$GRAFANA_MODE" in
  zu|frei) ;;
  *) echo "usage: AKS_CHECK_GRAFANA=zu|frei $0 [FQDN]  (got '$GRAFANA_MODE')" >&2; exit 2 ;;
esac
NAME="${1:-$FQDN_DEFAULT}"
case "$NAME" in
  ''|*[!a-z0-9.-]*) echo "usage: $0 [FQDN]  (lower-case host name, got '$NAME')" >&2; exit 2 ;;
esac
BASE="https://$NAME"

OKS=0
FAILS=0
report() {  # report OK|FEHLER CHECK DETAIL
  printf '%-6s %-24s %s\n' "$1" "$2" "$3"
  if [ "$1" = OK ]; then OKS=$((OKS + 1)); else FAILS=$((FAILS + 1)); fi
}
ok() { report OK "$1" "${2:-}"; }
fail() { report FEHLER "$1" "${2:-}"; }

if ! command -v curl >/dev/null 2>&1; then
  fail tools "curl fehlt"
  echo "aks-check: 0 OK, 1 FEHLER ($NAME)"
  exit 1
fi

TMP="$(mktemp -d "${TMPDIR:-/tmp}/aks-check.XXXXXX")" || exit 2
cleanup() { rm -f "$TMP"/*; rmdir "$TMP"; }
trap cleanup EXIT
printf '\000\000\000\000\000' > "$TMP/grpc-empty"  # one empty gRPC message frame

# -q must stay the first argument: curl then ignores ~/.curlrc ($CURL_HOME, XDG), so an
# "insecure" or proxy line there cannot turn the verified TLS check into a false OK
CURL_OPTS=(-q -sS --connect-timeout 5 --max-time 20 -A aks-check)

fetch() {  # fetch KEY URL [CURL ARGS...] -> prints the HTTP code (000 = no answer);
  # headers in $TMP/KEY.h, body in $TMP/KEY.b, curl's error text in $TMP/KEY.e
  local key="$1" url="$2" code
  shift 2
  : > "$TMP/$key.h"
  : > "$TMP/$key.b"
  code="$(curl "${CURL_OPTS[@]}" "$@" -D "$TMP/$key.h" -o "$TMP/$key.b" -w '%{http_code}' \
    "$url" 2>"$TMP/$key.e")"
  printf '%s' "${code:-000}"
}

header() {  # header KEY NAME -> value of the last response header NAME (lower case)
  tr -d '\r' < "$TMP/$1.h" | awk -v n="$2" '
    index($0, ":") > 1 {
      k = tolower(substr($0, 1, index($0, ":") - 1))
      if (k == n) { v = substr($0, index($0, ":") + 1); sub(/^[ \t]+/, "", v); val = v }
    }
    END { print val }'
}

curl_error() {  # curl_error KEY -> curl's error message in one line
  tr '\n' ' ' < "$TMP/$1.e" | sed 's/ *$//'
}

body_has() {  # body_has KEY ERE -> 0 when the body matches (case-insensitive)
  grep -Eiq -- "$2" "$TMP/$1.b"
}

# ---------------------------------------------------------------- name and TLS

root_code="$(fetch root "$BASE/")"
if [ "$root_code" = 000 ]; then
  fail "tls" "keine verifizierte HTTPS-Verbindung: $(curl_error root)"
elif ! command -v openssl >/dev/null 2>&1; then
  fail "tls" "curl verifiziert, openssl fehlt (Ablaufdatum ungeprüft)"
else
  openssl s_client -connect "$NAME:443" -servername "$NAME" </dev/null 2>/dev/null \
    | openssl x509 -outform PEM > "$TMP/cert.pem" 2>/dev/null
  issuer="$(openssl x509 -in "$TMP/cert.pem" -noout -issuer 2>/dev/null | sed 's/^issuer= *//')"
  not_after="$(openssl x509 -in "$TMP/cert.pem" -noout -enddate 2>/dev/null | sed 's/^notAfter=//')"
  if [ -z "$not_after" ]; then
    fail "tls" "curl verifiziert, Zertifikat per openssl nicht lesbar"
  elif openssl x509 -in "$TMP/cert.pem" -noout -checkend $((CERT_MIN_DAYS * 86400)) \
      >/dev/null 2>&1; then
    ok "tls" "verifiziert; $issuer; bis $not_after"
  else
    fail "tls" "läuft in weniger als $CERT_MIN_DAYS Tagen ab: bis $not_after (4.3)"
  fi
fi

if [ "$root_code" = 200 ]; then
  ok "sam /" "200"
else
  fail "sam /" "HTTP $root_code statt 200"
fi

detail=""
bad=""
for path in "/" "/kasse?till=$TILL"; do
  code="$(fetch redirect "http://$NAME$path")"
  location="$(header redirect location)"
  detail="$detail $path=$code"
  case "$code $location" in
    "308 https://$NAME/"*) ;;
    *) bad="$bad $path: HTTP $code ${location:-ohne Location};" ;;
  esac
done
if [ -z "$bad" ]; then
  ok "http -> https 308" "${detail# }"
else
  fail "http -> https 308" "${bad# }"
fi

# ---------------------------------------------------------------- gpos pages

kasse_code="$(fetch kasse "$BASE/kasse?till=$TILL")"
if [ "$kasse_code" = 200 ] && body_has kasse '<title>Kasse'; then
  ok "/kasse" "200, Titel Kasse"
else
  fail "/kasse" "HTTP $kasse_code, Titel: $(grep -o '<title>[^<]*' "$TMP/kasse.b" | head -1)"
fi

monitor_code="$(fetch monitor "$BASE/monitor")"
if [ "$monitor_code" = 200 ] && body_has monitor '<title>Messemonitor'; then
  ok "/monitor" "200, Titel Messemonitor"
else
  fail "/monitor" "HTTP $monitor_code, Titel: $(grep -o '<title>[^<]*' "$TMP/monitor.b" | head -1)"
fi

state_code="$(fetch state "$BASE/api/state?till=$TILL")"
state_type="$(header state content-type)"
case "$state_code $state_type" in
  "200 application/json"*)
    if body_has state '"till"'; then ok "/api/state" "200, JSON"
    else fail "/api/state" "200, aber kein Kassenstand im JSON"; fi ;;
  *) fail "/api/state" "HTTP $state_code, ${state_type:-ohne Content-Type}" ;;
esac

cookies=""
case "$kasse_code $monitor_code $state_code" in
  *000*) cookies=" (keine Antwort)" ;;
esac
for key in kasse monitor state; do
  [ -n "$(header "$key" set-cookie)" ] && cookies="$cookies $key"
done
if [ -z "$cookies" ]; then
  ok "kein Cookie (gpos)" "/kasse, /monitor, /api/state ohne Set-Cookie"
else
  fail "kein Cookie (gpos)" "Set-Cookie bei:$cookies"
fi

bad=""
for key in kasse root; do
  hsts="$(header "$key" strict-transport-security)"
  hsts_lc="$(printf '%s' "$hsts" | tr '[:upper:]' '[:lower:]')"
  case "$hsts_lc" in
    *includesubdomains*|*preload*) bad="$bad $key: $hsts;" ;;
    *max-age=[1-9]*) ;;
    *) bad="$bad $key: ${hsts:-kein HSTS-Header};" ;;
  esac
done
if [ -z "$bad" ]; then
  ok "hsts" "$(header kasse strict-transport-security), ohne includeSubDomains"
else
  fail "hsts" "${bad# }"
fi

# SSE: headers and the hello event must arrive at once (no buffering); curl stops
# after 4 s (exit 28), the stream itself never ends
events_code="$(fetch events "$BASE/api/events" -N --max-time 4)"
events_type="$(header events content-type)"
if [ "$events_code" = 200 ] && [ "${events_type%%;*}" = text/event-stream ] \
    && body_has events '^event: hello'; then
  ok "/api/events (SSE)" "200, text/event-stream, hello sofort"
else
  fail "/api/events (SSE)" "HTTP $events_code, ${events_type:-ohne Content-Type}, hello $(
    body_has events '^event: hello' && echo da || echo fehlt)"
fi

# ---------------------------------------------------------------- Keycloak

oidc_code="$(fetch oidc "$BASE/auth/realms/solace-lab/.well-known/openid-configuration")"
if command -v jq >/dev/null 2>&1; then
  issuer="$(jq -r '.issuer // empty' "$TMP/oidc.b" 2>/dev/null)"
else
  issuer="$(tr -d '\n' < "$TMP/oidc.b" | sed -n 's/.*"issuer" *: *"\([^"]*\)".*/\1/p')"
fi
if [ "$oidc_code" = 200 ] && [ "$issuer" = "$BASE/auth/realms/solace-lab" ]; then
  ok "oidc-issuer" "$issuer"
else
  fail "oidc-issuer" "HTTP $oidc_code, issuer '${issuer}' statt '$BASE/auth/realms/solace-lab'"
fi

login_challenge() {  # login_challenge KEY -> 0 when a WWW-Authenticate header asks for
  # Basic or Digest (SAM and Keycloak never do: SAM's API answers with Bearer at most)
  tr -d '\r' < "$TMP/$1.h" \
    | grep -Eiq '^www-authenticate:[[:space:]]*(.*,[[:space:]]*)?(basic|digest)([[:space:]]|,|$)'
}

closed() {  # closed CHECK ERE PATH... -> OK when no PATH answers with content matching ERE
  # (body or Location) and none answers with a Basic/Digest login challenge
  local check="$1" marker="$2" path code location detail="" bad=""
  shift 2
  for path in "$@"; do
    code="$(fetch closed "$BASE$path")"
    location="$(header closed location)"
    if [ "$code" = 000 ]; then
      bad="$bad $path: keine Antwort ($(curl_error closed));"
    elif body_has closed "$marker" || printf '%s' "$location" | grep -Eiq -- "$marker"; then
      bad="$bad $path: HTTP $code mit Inhalt des Ziels;"
    elif login_challenge closed; then
      bad="$bad $path: HTTP $code mit Login-Abfrage ($(header closed www-authenticate));"
    else
      detail="$detail $path=$code"
    fi
  done
  if [ -z "$bad" ]; then ok "$check" "zu:$detail"; else fail "$check" "${bad# }"; fi
}

closed "keycloak-admin zu" '<title>[^<]*keycloak|/admin/master/console' /auth/admin/
closed "keycloak master zu" '"realm" *: *"master"|/realms/master/protocol' \
  /auth/realms/master/ /auth/realms/master/.well-known/openid-configuration
# Grafana behind Traefik's ipAllowList: outside the list Traefik answers 403 before
# Grafana (an absent route lands at SAM: also closed); inside it Grafana answers
grafana_marker='<title>[^<]*grafana|"database" *: *"ok"'
if [ "$GRAFANA_MODE" = zu ]; then
  fails_before=$FAILS
  closed "grafana allowlist" "$grafana_marker" /grafana/login /grafana/api/health
  [ "$FAILS" -gt "$fails_before" ] &&
    echo "Hinweis: steht diese IP in der Grafana-Allowlist, dann AKS_CHECK_GRAFANA=frei $0" >&2
else
  code="$(fetch grafana "$BASE/grafana/api/health")"
  if [ "$code" = 200 ] && body_has grafana '"database" *: *"ok"'; then
    ok "grafana allowlist" "frei für diese IP: /grafana/api/health=200"
  elif [ "$code" = 403 ]; then
    fail "grafana allowlist" "HTTP 403: diese IP ist nicht in der Allowlist (grafana_allow)"
  else
    fail "grafana allowlist" "HTTP $code ohne Grafana: Route fehlt (grafana_allow)"
  fi
fi
closed "prometheus zu" '<title>[^<]*prometheus|"goVersion"' /graph \
  /prometheus/api/v1/status/buildinfo
closed "traefik-dashboard zu" '<title>[^<]*traefik|"routers" *:' /dashboard/ /api/rawdata
# SEMP v2 needs Basic auth: without credentials a routed broker answers 401 with its
# JSON error envelope ("meta" ... "responseCode"), never with sempVersion
closed "semp zu" 'sempVersion|"responseCode" *: *[0-9]' /SEMP/v2/monitor/about/api

# ---------------------------------------------------------------- gRPC

if ! command -v grpcurl >/dev/null 2>&1; then
  fail "grpcurl list" "grpcurl fehlt"
elif grpcurl -max-time 15 "$NAME:443" list > "$TMP/grpc-list" 2> "$TMP/grpc-list.e"; then
  services=""
  for svc in "$PURCHASE" "$WWS" "$LOYALTY"; do
    grep -qx -- "$svc" "$TMP/grpc-list" && services="$services ${svc##*.}"
  done
  if grep -qx -- "$PURCHASE" "$TMP/grpc-list"; then
    ok "grpcurl list" "Reflection:$services"
  else
    fail "grpcurl list" "PurchaseTransactionService fehlt (gefunden:${services:- nichts})"
  fi
else
  fail "grpcurl list" "$(tr '\n' ' ' < "$TMP/grpc-list.e" | cut -c1-160)"
fi

grpc_probe() {  # grpc_probe KEY PATH -> HTTP code of a gRPC POST with one empty message
  fetch "$1" "$BASE$2" --http2 -X POST -H 'content-type: application/grpc' \
    -H 'te: trailers' --data-binary @"$TMP/grpc-empty"
}

for entry in "purchase $PURCHASE" "wws $WWS" "loyalty $LOYALTY"; do
  label="grpc ${entry%% *}"
  svc="${entry#* }"
  code="$(grpc_probe probe "/$svc/AksCheckNoSuchMethod")"
  type="$(header probe content-type)"
  status="$(header probe grpc-status)"
  case "$type" in
    application/grpc*) ok "$label" "/$svc/ -> gRPC-Server (grpc-status $status)" ;;
    *) fail "$label" "/$svc/ -> kein gRPC-Server: HTTP $code, ${type:-ohne Content-Type}" ;;
  esac
done

code="$(grpc_probe health /grpc.health.v1.Health/Check)"
type="$(header health content-type)"
status="$(header health grpc-status)"
case "$code $type" in
  000*) fail "grpc health zu" "keine Antwort ($(curl_error health))" ;;
  *application/grpc*) fail "grpc health zu" "von außen erreichbar (grpc-status $status)" ;;
  *) ok "grpc health zu" "HTTP $code, kein gRPC (${type:-ohne Content-Type})" ;;
esac

echo "aks-check: $OKS OK, $FAILS FEHLER ($NAME)"
[ "$FAILS" -eq 0 ]
