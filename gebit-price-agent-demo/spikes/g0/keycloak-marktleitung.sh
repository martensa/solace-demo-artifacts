#!/bin/bash
set -euo pipefail

# Gate 0 (O2, 2026-11-11): Keycloak group and demo user for the
# approver persona "Marktleitung" in the solace-lab realm.
#   ./keycloak-marktleitung.sh            create (idempotent)
#   ./keycloak-marktleitung.sh --delete   remove user and group
# Same conventions as agent-mesh-deployment/scripts/
# setup-keycloak-users.sh (admin token from that .env, password =
# username, email <user>@solace.lab, group = SAM claim value).
# The SAM side (role gpos_marktleitung, claim mapping, direct grant)
# is in ./rbac (sam config apply -m manifest-rbac.yaml).
#
# Optional environment (unset = the local lab, unchanged), as in
# the agent-mesh-deployment setup scripts (aks_kc in
# infra/aks/aks.sh sets them for AKS):
#   SAM_ENV_FILE  env file instead of agent-mesh-deployment/.env;
#                 it must then set KEYCLOAK_URL itself (no lab
#                 default), e.g. the AKS port-forward
#                 http://127.0.0.1:18081/auth
# KEYCLOAK_ADMIN_PASSWORD from the environment is used when the env
# file does not set it.

INFRA_DIR="$(cd "$(dirname "$0")/../../../agent-mesh-deployment" && pwd)"
ENV_FILE="${SAM_ENV_FILE:-$INFRA_DIR/.env}"
[ -f "$ENV_FILE" ] || { echo "ERROR: $ENV_FILE missing" >&2; exit 1; }
# shellcheck disable=SC1090,SC1091
. "$ENV_FILE"
if [ -n "${SAM_ENV_FILE:-}" ] && [ -z "${KEYCLOAK_URL:-}" ]; then
  echo "ERROR: KEYCLOAK_URL is not set in $ENV_FILE" >&2; exit 1
fi
if [ -n "${SAM_ENV_FILE:-}" ] && [ -z "${KEYCLOAK_ADMIN_PASSWORD:-}" ]; then
  echo "ERROR: KEYCLOAK_ADMIN_PASSWORD is not set (environment or $ENV_FILE)" >&2
  exit 1
fi
KEYCLOAK_URL="${KEYCLOAK_URL:-https://auth.solace.lab}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-solace-lab}"
GROUP="marktleitung"
USER="marktleitung"
DELETE=0
[ "${1:-}" = "--delete" ] && DELETE=1

# With SAM_ENV_FILE (a remote Keycloak; aks_kc passes the admin
# password from the Key Vault) neither the password nor the admin
# token ever goes into an argv: the password reaches curl on stdin,
# the bearer header through a curl config on a file descriptor
# (kc_curl). The lab keeps its argv as it always was.
if [ -n "${SAM_ENV_FILE:-}" ]; then
  TOKEN=$(printf '%s' "$KEYCLOAK_ADMIN_PASSWORD" | curl -sk -X POST \
    "${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=password" -d "client_id=admin-cli" \
    --data-urlencode "username=${KEYCLOAK_ADMIN_USER}" \
    --data-urlencode "password@-" \
    | jq -r '.access_token // empty')
else
  TOKEN=$(curl -sk -X POST \
    "${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=password" -d "client_id=admin-cli" \
    --data-urlencode "username=${KEYCLOAK_ADMIN_USER}" \
    --data-urlencode "password=${KEYCLOAK_ADMIN_PASSWORD}" \
    | jq -r '.access_token // empty')
fi
[ -n "$TOKEN" ] || { echo "ERROR: no Keycloak admin token" >&2; exit 1; }
BASE="${KEYCLOAK_URL}/admin/realms/${KEYCLOAK_REALM}"
if [ -n "${SAM_ENV_FILE:-}" ]; then
  case "$TOKEN" in
    *[!A-Za-z0-9._~+/=-]*)
      echo "ERROR: the admin token has unexpected characters" >&2; exit 1 ;;
  esac
  AUTH=()
else
  AUTH=(-H "Authorization: Bearer ${TOKEN}")
fi
kc_curl() {   # curl; remote: the bearer header from a config fd, not argv
  if [ -n "${SAM_ENV_FILE:-}" ]; then
    curl --config <(printf 'header = "Authorization: Bearer %s"\n' "$TOKEN") "$@"
  else
    curl "$@"
  fi
}

group_id() {
  kc_curl -sk "${BASE}/groups?search=${GROUP}&exact=true" ${AUTH[@]+"${AUTH[@]}"} \
    | jq -r --arg n "$GROUP" '.[] | select(.name==$n) | .id' | head -1
}
user_id() {
  kc_curl -sk "${BASE}/users?username=${USER}&exact=true" ${AUTH[@]+"${AUTH[@]}"} \
    | jq -r --arg n "$USER" '.[] | select(.username==$n) | .id' | head -1
}

if [ "$DELETE" -eq 1 ]; then
  U=$(user_id); G=$(group_id)
  [ -n "$U" ] && kc_curl -sk -o /dev/null -w "delete user: %{http_code}\n" \
    -X DELETE "${BASE}/users/${U}" ${AUTH[@]+"${AUTH[@]}"}
  [ -n "$G" ] && kc_curl -sk -o /dev/null -w "delete group: %{http_code}\n" \
    -X DELETE "${BASE}/groups/${G}" ${AUTH[@]+"${AUTH[@]}"}
  exit 0
fi

G=$(group_id)
if [ -z "$G" ]; then
  code=$(kc_curl -sk -o /dev/null -w "%{http_code}" -X POST "${BASE}/groups" \
    ${AUTH[@]+"${AUTH[@]}"} -H "Content-Type: application/json" \
    -d "{\"name\":\"${GROUP}\"}")
  [ "$code" = "201" ] || { echo "ERROR: create group (HTTP $code)" >&2; exit 1; }
  G=$(group_id)
  echo "Group '${GROUP}' created (${G})."
else
  echo "Group '${GROUP}' exists (${G})."
fi

U=$(user_id)
if [ -z "$U" ]; then
  BODY=$(jq -n --arg u "$USER" '{
    username: $u, email: ($u + "@solace.lab"),
    firstName: "Marktleitung", lastName: "Solace Lab",
    emailVerified: true, enabled: true,
    credentials: [{type: "password", value: $u, temporary: false}]}')
  code=$(kc_curl -sk -o /dev/null -w "%{http_code}" -X POST "${BASE}/users" \
    ${AUTH[@]+"${AUTH[@]}"} -H "Content-Type: application/json" -d "$BODY")
  [ "$code" = "201" ] || { echo "ERROR: create user (HTTP $code)" >&2; exit 1; }
  U=$(user_id)
  echo "User '${USER}' created (${U})."
else
  echo "User '${USER}' exists (${U})."
fi

code=$(kc_curl -sk -o /dev/null -w "%{http_code}" -X PUT \
  "${BASE}/users/${U}/groups/${G}" ${AUTH[@]+"${AUTH[@]}"})
[ "$code" = "204" ] || { echo "ERROR: join group (HTTP $code)" >&2; exit 1; }
echo "User '${USER}' is in group '${GROUP}'."
