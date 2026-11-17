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

INFRA_DIR="$(cd "$(dirname "$0")/../../../agent-mesh-deployment" && pwd)"
[ -f "$INFRA_DIR/.env" ] || { echo "ERROR: $INFRA_DIR/.env missing" >&2; exit 1; }
# shellcheck disable=SC1091
. "$INFRA_DIR/.env"
KEYCLOAK_URL="${KEYCLOAK_URL:-https://auth.solace.lab}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-solace-lab}"
GROUP="marktleitung"
USER="marktleitung"
DELETE=0
[ "${1:-}" = "--delete" ] && DELETE=1

TOKEN=$(curl -sk -X POST \
  "${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" -d "client_id=admin-cli" \
  --data-urlencode "username=${KEYCLOAK_ADMIN_USER}" \
  --data-urlencode "password=${KEYCLOAK_ADMIN_PASSWORD}" \
  | jq -r '.access_token // empty')
[ -n "$TOKEN" ] || { echo "ERROR: no Keycloak admin token" >&2; exit 1; }
BASE="${KEYCLOAK_URL}/admin/realms/${KEYCLOAK_REALM}"
AUTH=(-H "Authorization: Bearer ${TOKEN}")

group_id() {
  curl -sk "${BASE}/groups?search=${GROUP}&exact=true" "${AUTH[@]}" \
    | jq -r --arg n "$GROUP" '.[] | select(.name==$n) | .id' | head -1
}
user_id() {
  curl -sk "${BASE}/users?username=${USER}&exact=true" "${AUTH[@]}" \
    | jq -r --arg n "$USER" '.[] | select(.username==$n) | .id' | head -1
}

if [ "$DELETE" -eq 1 ]; then
  U=$(user_id); G=$(group_id)
  [ -n "$U" ] && curl -sk -o /dev/null -w "delete user: %{http_code}\n" \
    -X DELETE "${BASE}/users/${U}" "${AUTH[@]}"
  [ -n "$G" ] && curl -sk -o /dev/null -w "delete group: %{http_code}\n" \
    -X DELETE "${BASE}/groups/${G}" "${AUTH[@]}"
  exit 0
fi

G=$(group_id)
if [ -z "$G" ]; then
  code=$(curl -sk -o /dev/null -w "%{http_code}" -X POST "${BASE}/groups" \
    "${AUTH[@]}" -H "Content-Type: application/json" \
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
  code=$(curl -sk -o /dev/null -w "%{http_code}" -X POST "${BASE}/users" \
    "${AUTH[@]}" -H "Content-Type: application/json" -d "$BODY")
  [ "$code" = "201" ] || { echo "ERROR: create user (HTTP $code)" >&2; exit 1; }
  U=$(user_id)
  echo "User '${USER}' created (${U})."
else
  echo "User '${USER}' exists (${U})."
fi

code=$(curl -sk -o /dev/null -w "%{http_code}" -X PUT \
  "${BASE}/users/${U}/groups/${G}" "${AUTH[@]}")
[ "$code" = "204" ] || { echo "ERROR: join group (HTTP $code)" >&2; exit 1; }
echo "User '${USER}' is in group '${GROUP}'."
