#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Load environment variables -----------------------------------
if [ ! -f "$PROJECT_DIR/.env" ]; then
  echo "No .env file found. Copy .env.example to .env first."
  exit 1
fi

# shellcheck source=/dev/null
. "$PROJECT_DIR/.env"

# --- Defaults -----------------------------------------------------
KEYCLOAK_URL="${KEYCLOAK_URL:-https://auth.solace.lab}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-solace-lab}"
KEYCLOAK_ADMIN_USER="${KEYCLOAK_ADMIN_USER:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
OM_CLIENT_ID="${KEYCLOAK_CLIENT_ID:-openmetadata}"
OM_DNS_NAME="openmetadata.solace.lab"

# OM completes the OIDC code flow at /callback. Register the wildcard
# so any query parameters and follow-up paths added by OM are accepted.

# --- Check dependencies -------------------------------------------
if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required but not installed."
  echo "Install with: brew install jq (macOS) or apt install jq (Linux)"
  exit 1
fi

# --- Obtain admin token -------------------------------------------
echo "Obtaining Keycloak admin token from ${KEYCLOAK_URL} ..."
TOKEN_RESPONSE=$(curl -sk -X POST \
  "${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=admin-cli" \
  -d "username=${KEYCLOAK_ADMIN_USER}" \
  -d "password=${KEYCLOAK_ADMIN_PASSWORD}")

TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token // empty')

if [ -z "$TOKEN" ]; then
  echo "ERROR: Failed to obtain admin token. Response:"
  echo "$TOKEN_RESPONSE"
  exit 1
fi

BASE="${KEYCLOAK_URL}/admin/realms/${KEYCLOAK_REALM}"

# --- Force realm defaultSignatureAlgorithm to RS256 ---------------
# OM 1.6.5's JwtFilter unconditionally casts the JWKS-resolved
# public key to RSAPublicKey (JwtFilter.java:231). If the realm's
# default signature algorithm is ES256 (Keycloak's out-of-the-box
# choice on some realms), every issued ID token is EC-signed and
# OM throws ClassCastException on the OIDC callback. Setting the
# realm default to RS256 makes Keycloak sign with the RSA key
# instead. The realm still auto-recreates an `ecdsa-generated`
# fallback provider whenever we delete it, so we leave the
# provider alone -- it just stops being used for signing.
REALM_CURRENT_ALG=$(curl -sk "${BASE}" \
  -H "Authorization: Bearer ${TOKEN}" \
  | jq -r '.defaultSignatureAlgorithm // empty')
if [ "${REALM_CURRENT_ALG}" != "RS256" ]; then
  echo "Setting realm defaultSignatureAlgorithm to RS256 (was: ${REALM_CURRENT_ALG:-unset}) ..."
  curl -sk -X PUT \
    "${BASE}" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{"defaultSignatureAlgorithm":"RS256"}' \
    -o /dev/null
fi

# --- Helper: find client UUID by clientId -------------------------
get_client_uuid() {
  curl -sk "${BASE}/clients?clientId=${OM_CLIENT_ID}" \
    -H "Authorization: Bearer ${TOKEN}" \
    | jq -r --arg c "$OM_CLIENT_ID" \
        '.[] | select(.clientId==$c) | .id' \
    | head -1
}

# --- Check if client already exists -------------------------------
CLIENT_UUID=$(get_client_uuid)

if [ -n "$CLIENT_UUID" ]; then
  echo "Client '${OM_CLIENT_ID}' already exists (${CLIENT_UUID})."
  echo "Fetching client secret ..."
  SECRET=$(curl -sk \
    "${BASE}/clients/${CLIENT_UUID}/client-secret" \
    -H "Authorization: Bearer ${TOKEN}" \
    | jq -r '.value // empty')
  echo ""
  echo "Client ID:     ${OM_CLIENT_ID}"
  echo "Client Secret: ${SECRET}"
  echo ""
  echo "Set this in your .env file:"
  echo "  KEYCLOAK_CLIENT_SECRET=${SECRET}"
  exit 0
fi

# --- Create the OIDC client --------------------------------------
echo "Creating OIDC client '${OM_CLIENT_ID}' ..."
HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" -X POST \
  "${BASE}/clients" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{
    \"clientId\": \"${OM_CLIENT_ID}\",
    \"name\": \"OpenMetadata\",
    \"description\": \"OIDC client for OpenMetadata (Solace Lab)\",
    \"enabled\": true,
    \"protocol\": \"openid-connect\",
    \"publicClient\": false,
    \"clientAuthenticatorType\": \"client-secret\",
    \"standardFlowEnabled\": true,
    \"directAccessGrantsEnabled\": false,
    \"serviceAccountsEnabled\": false,
    \"redirectUris\": [\"https://${OM_DNS_NAME}/*\"],
    \"webOrigins\": [\"https://${OM_DNS_NAME}\"],
    \"defaultClientScopes\": [
      \"openid\", \"email\", \"profile\"
    ]
  }")

if [ "$HTTP_CODE" != "201" ]; then
  echo "ERROR: Failed to create client (HTTP ${HTTP_CODE})."
  exit 1
fi

# --- Look up client UUID after creation ---------------------------
CLIENT_UUID=$(get_client_uuid)

if [ -z "$CLIENT_UUID" ]; then
  echo "ERROR: Client created but UUID lookup failed."
  exit 1
fi

# --- Add group membership mapper ---------------------------------
# Not required for the basic admin-by-email login path, but the
# 'groups' claim is the conventional carrier if RBAC mapping
# (useRolesFromProvider) is enabled later. Cheap to add now.
echo "Adding group membership protocol mapper ..."
curl -sk -o /dev/null -X POST \
  "${BASE}/clients/${CLIENT_UUID}/protocol-mappers/models" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"group-membership\",
    \"protocol\": \"openid-connect\",
    \"protocolMapper\": \"oidc-group-membership-mapper\",
    \"config\": {
      \"full.path\": \"false\",
      \"id.token.claim\": \"true\",
      \"access.token.claim\": \"true\",
      \"userinfo.token.claim\": \"true\",
      \"claim.name\": \"groups\"
    }
  }"

# --- Fetch client secret ------------------------------------------
SECRET=$(curl -sk \
  "${BASE}/clients/${CLIENT_UUID}/client-secret" \
  -H "Authorization: Bearer ${TOKEN}" \
  | jq -r '.value // empty')

echo ""
echo "OIDC client created successfully."
echo ""
echo "Client ID:     ${OM_CLIENT_ID}"
echo "Client Secret: ${SECRET}"
echo ""
echo "Set this in your .env file:"
echo "  KEYCLOAK_CLIENT_SECRET=${SECRET}"
