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
SAM_CLIENT_ID="${KEYCLOAK_CLIENT_ID:-solace-agent-mesh}"
SAM_DNS_NAME="sam.solace.lab"

# Note: The SAM Helm chart computes the redirect URI automatically
# (actual path: /api/v1/auth/callback). We register
# https://<SAM_DNS_NAME>/* as redirect URI wildcard so any callback
# path issued by SAM is accepted by Keycloak.

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

# --- Helper: find client UUID by clientId -------------------------
get_client_uuid() {
  curl -sk "${BASE}/clients?clientId=${SAM_CLIENT_ID}" \
    -H "Authorization: Bearer ${TOKEN}" \
    | jq -r --arg c "$SAM_CLIENT_ID" \
        '.[] | select(.clientId==$c) | .id' \
    | head -1
}

# --- Check if client already exists -------------------------------
CLIENT_UUID=$(get_client_uuid)

if [ -n "$CLIENT_UUID" ]; then
  echo "Client '${SAM_CLIENT_ID}' already exists (${CLIENT_UUID})."
  echo "Fetching client secret ..."
  SECRET=$(curl -sk \
    "${BASE}/clients/${CLIENT_UUID}/client-secret" \
    -H "Authorization: Bearer ${TOKEN}" \
    | jq -r '.value // empty')
  echo ""
  echo "Client ID:     ${SAM_CLIENT_ID}"
  echo "Client Secret: ${SECRET}"
  echo ""
  echo "Set this in your .env file:"
  echo "  KEYCLOAK_CLIENT_SECRET=${SECRET}"
  exit 0
fi

# --- Create the OIDC client --------------------------------------
echo "Creating OIDC client '${SAM_CLIENT_ID}' ..."
HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" -X POST \
  "${BASE}/clients" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{
    \"clientId\": \"${SAM_CLIENT_ID}\",
    \"name\": \"Solace Agent Mesh\",
    \"description\": \"OIDC client for Solace Agent Mesh (SAM)\",
    \"enabled\": true,
    \"protocol\": \"openid-connect\",
    \"publicClient\": false,
    \"clientAuthenticatorType\": \"client-secret\",
    \"standardFlowEnabled\": true,
    \"directAccessGrantsEnabled\": false,
    \"serviceAccountsEnabled\": false,
    \"redirectUris\": [\"https://${SAM_DNS_NAME}/*\"],
    \"webOrigins\": [\"https://${SAM_DNS_NAME}\"],
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
# SAM RBAC expects a "groups" claim in the ID token. A silently
# failed mapper write would break all group-based role mappings,
# so the HTTP status is checked.
echo "Adding group membership protocol mapper ..."
HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" -X POST \
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
  }")

if [ "$HTTP_CODE" != "201" ]; then
  echo "ERROR: Failed to add group membership mapper (HTTP ${HTTP_CODE})."
  echo "SAM group-based RBAC will not work without the 'groups' claim."
  exit 1
fi

# --- Add offline_access as optional client scope -----------------
# SAM requests offline_access to receive refresh tokens
echo "Adding 'offline_access' as optional client scope ..."
OFFLINE_ACCESS_ID=$(curl -sk "${BASE}/client-scopes" \
  -H "Authorization: Bearer ${TOKEN}" \
  | jq -r '.[] | select(.name=="offline_access") | .id')

if [ -n "$OFFLINE_ACCESS_ID" ]; then
  HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" -X PUT \
    "${BASE}/clients/${CLIENT_UUID}/optional-client-scopes/${OFFLINE_ACCESS_ID}" \
    -H "Authorization: Bearer ${TOKEN}")
  if [ "$HTTP_CODE" != "204" ]; then
    echo "WARNING: adding offline_access scope failed (HTTP ${HTTP_CODE})."
    echo "Refresh tokens may be unavailable to SAM."
  fi
else
  echo "WARNING: offline_access scope not found in realm."
fi

# --- Fetch client secret ------------------------------------------
SECRET=$(curl -sk \
  "${BASE}/clients/${CLIENT_UUID}/client-secret" \
  -H "Authorization: Bearer ${TOKEN}" \
  | jq -r '.value // empty')

echo ""
echo "OIDC client created successfully."
echo ""
echo "Client ID:     ${SAM_CLIENT_ID}"
echo "Client Secret: ${SECRET}"
echo ""
echo "Set this in your .env file:"
echo "  KEYCLOAK_CLIENT_SECRET=${SECRET}"
