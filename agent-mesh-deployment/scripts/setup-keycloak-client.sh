#!/bin/sh
set -e

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
SAM_REDIRECT_URI="${KEYCLOAK_REDIRECT_URI:-https://sam.solace.lab/callback}"
SAM_DNS_NAME="${SAM_DNS_NAME:-sam.solace.lab}"

# --- Obtain admin token -------------------------------------------
echo "Obtaining Keycloak admin token ..."
TOKEN=$(curl -sf -X POST \
  "${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=admin-cli" \
  -d "username=${KEYCLOAK_ADMIN_USER}" \
  -d "password=${KEYCLOAK_ADMIN_PASSWORD}" \
  | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')

if [ -z "$TOKEN" ]; then
  echo "ERROR: Failed to obtain admin token."
  echo "Check KEYCLOAK_URL, KEYCLOAK_ADMIN_USER, and"
  echo "KEYCLOAK_ADMIN_PASSWORD in .env."
  exit 1
fi

BASE="${KEYCLOAK_URL}/admin/realms/${KEYCLOAK_REALM}"

# --- Check if client already exists -------------------------------
EXISTING=$(curl -sf -o /dev/null -w "%{http_code}" \
  "${BASE}/clients?clientId=${SAM_CLIENT_ID}" \
  -H "Authorization: Bearer ${TOKEN}")

if [ "$EXISTING" = "200" ]; then
  CLIENT_UUID=$(curl -sf \
    "${BASE}/clients?clientId=${SAM_CLIENT_ID}" \
    -H "Authorization: Bearer ${TOKEN}" \
    | sed -n 's/.*"id":"\([^"]*\)".*/\1/p' | head -1)

  if [ -n "$CLIENT_UUID" ]; then
    echo "Client '${SAM_CLIENT_ID}' already exists (${CLIENT_UUID})."
    echo "Fetching client secret ..."
    SECRET=$(curl -sf \
      "${BASE}/clients/${CLIENT_UUID}/client-secret" \
      -H "Authorization: Bearer ${TOKEN}" \
      | sed -n 's/.*"value":"\([^"]*\)".*/\1/p')
    echo ""
    echo "Client ID:     ${SAM_CLIENT_ID}"
    echo "Client Secret: ${SECRET}"
    echo ""
    echo "Set these in your .env file:"
    echo "  KEYCLOAK_CLIENT_ID=${SAM_CLIENT_ID}"
    echo "  KEYCLOAK_CLIENT_SECRET=${SECRET}"
    exit 0
  fi
fi

# --- Create the OIDC client --------------------------------------
echo "Creating OIDC client '${SAM_CLIENT_ID}' ..."
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" -X POST \
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

# --- Get client UUID ----------------------------------------------
CLIENT_UUID=$(curl -sf \
  "${BASE}/clients?clientId=${SAM_CLIENT_ID}" \
  -H "Authorization: Bearer ${TOKEN}" \
  | sed -n 's/.*"id":"\([^"]*\)".*/\1/p' | head -1)

if [ -z "$CLIENT_UUID" ]; then
  echo "ERROR: Client created but UUID lookup failed."
  exit 1
fi

# --- Add group membership mapper ---------------------------------
# SAM RBAC expects a "groups" claim in the ID token
echo "Adding group membership protocol mapper ..."
curl -sf -o /dev/null -X POST \
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
SECRET=$(curl -sf \
  "${BASE}/clients/${CLIENT_UUID}/client-secret" \
  -H "Authorization: Bearer ${TOKEN}" \
  | sed -n 's/.*"value":"\([^"]*\)".*/\1/p')

echo ""
echo "OIDC client created successfully."
echo ""
echo "Client ID:     ${SAM_CLIENT_ID}"
echo "Client Secret: ${SECRET}"
echo ""
echo "Set these in your .env file:"
echo "  KEYCLOAK_CLIENT_ID=${SAM_CLIENT_ID}"
echo "  KEYCLOAK_CLIENT_SECRET=${SECRET}"
