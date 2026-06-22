#!/bin/bash
# Fetch the OpenMetadata ingestion-bot JWT and print it to stdout (only the
# token; all diagnostics go to stderr, so callers can `TOK=$(get-om-bot-token.sh)`).
#
# Lab flow (Keycloak custom-oidc): the OM REST API needs an admin-authenticated
# call to read the bot token. We temporarily enable Direct Access Grants on the
# OM OIDC client, do a password grant for the realm admin, read the bot token,
# and restore the client. The non-expiring ingestion-bot JWT is the result.
#
# For a NON-lab OM (no Keycloak access), skip this entirely and set
# OM_JWT_TOKEN directly in the connector .env.
#
# Overridable via env (lab defaults shown); also sources the OM deployment .env
# for the Keycloak client id + secret if present.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

log() { echo "[get-om-bot-token] $*" >&2; }

# Pull KEYCLOAK_* (incl. the OM client secret) from the OM deployment .env.
OM_DEPLOY_ENV="${OM_DEPLOY_ENV:-$PROJECT_DIR/../../openmetadata-deployment/.env}"
if [ -f "$OM_DEPLOY_ENV" ]; then
  # shellcheck source=/dev/null
  set -a; . "$OM_DEPLOY_ENV"; set +a
fi

KC_URL="${KEYCLOAK_URL:-https://auth.solace.lab}"
KC_REALM="${KEYCLOAK_REALM:-solace-lab}"
KC_ADMIN_USER="${KEYCLOAK_ADMIN_USER:-admin}"
KC_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
OM_CLIENT_ID="${KEYCLOAK_CLIENT_ID:-openmetadata}"
OM_CLIENT_SECRET="${KEYCLOAK_CLIENT_SECRET:-}"
OM_ADMIN_USER="${OM_ADMIN_USER:-admin}"
OM_ADMIN_PASSWORD="${OM_ADMIN_PASSWORD:-admin}"
# Host-reachable OM URL (the in-cluster service name is not resolvable here).
OM_URL="${OM_PUBLIC_URL:-https://openmetadata.solace.lab}"

command -v curl >/dev/null || { log "ERROR: curl not found"; exit 1; }
command -v jq   >/dev/null || { log "ERROR: jq not found";   exit 1; }
if [ -z "$OM_CLIENT_SECRET" ]; then
  log "ERROR: KEYCLOAK_CLIENT_SECRET is empty. Source openmetadata-deployment/.env"
  log "       (it is persisted there by the OM start.sh) or export it."
  exit 1
fi

log "Keycloak: $KC_URL realm=$KC_REALM  OM: $OM_URL"
MTOK=$(curl -sk -X POST "$KC_URL/realms/master/protocol/openid-connect/token" \
  -d grant_type=password -d client_id=admin-cli \
  -d "username=$KC_ADMIN_USER" -d "password=$KC_ADMIN_PASSWORD" | jq -r .access_token)
[ -n "$MTOK" ] && [ "$MTOK" != "null" ] || { log "ERROR: master admin login failed"; exit 1; }

CID=$(curl -sk "$KC_URL/admin/realms/$KC_REALM/clients?clientId=$OM_CLIENT_ID" \
  -H "Authorization: Bearer $MTOK" | jq -r '.[0].id')
[ -n "$CID" ] && [ "$CID" != "null" ] || { log "ERROR: OM client '$OM_CLIENT_ID' not found"; exit 1; }
CLIENT=$(curl -sk "$KC_URL/admin/realms/$KC_REALM/clients/$CID" -H "Authorization: Bearer $MTOK")

# Always restore the client's original directAccessGrants state on exit.
restore() {
  echo "$CLIENT" | jq '.directAccessGrantsEnabled=false' \
    | curl -sk -o /dev/null -X PUT "$KC_URL/admin/realms/$KC_REALM/clients/$CID" \
        -H "Authorization: Bearer $MTOK" -H "Content-Type: application/json" -d @- || true
}
trap restore EXIT

echo "$CLIENT" | jq '.directAccessGrantsEnabled=true' \
  | curl -sk -o /dev/null -X PUT "$KC_URL/admin/realms/$KC_REALM/clients/$CID" \
      -H "Authorization: Bearer $MTOK" -H "Content-Type: application/json" -d @-

ATOK=$(curl -sk -X POST "$KC_URL/realms/$KC_REALM/protocol/openid-connect/token" \
  -d grant_type=password -d "client_id=$OM_CLIENT_ID" -d "client_secret=$OM_CLIENT_SECRET" \
  -d "username=$OM_ADMIN_USER" -d "password=$OM_ADMIN_PASSWORD" -d scope=openid | jq -r .access_token)
[ -n "$ATOK" ] && [ "$ATOK" != "null" ] || { log "ERROR: realm admin password grant failed"; exit 1; }

BOTID=$(curl -sk "$OM_URL/api/v1/bots/name/ingestion-bot" -H "Authorization: Bearer $ATOK" \
  | jq -r '.botUser.id')
[ -n "$BOTID" ] && [ "$BOTID" != "null" ] || { log "ERROR: could not resolve ingestion-bot user id"; exit 1; }

JWT=$(curl -sk "$OM_URL/api/v1/users/token/$BOTID" -H "Authorization: Bearer $ATOK" | jq -r '.JWTToken')
[ -n "$JWT" ] && [ "$JWT" != "null" ] || { log "ERROR: failed to read ingestion-bot JWT"; exit 1; }

log "OK: fetched ingestion-bot JWT (len ${#JWT})"
printf '%s' "$JWT"
