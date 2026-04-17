#!/bin/sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Load environment variables -----------------------------------
if [ -f "$PROJECT_DIR/.env" ]; then
  # shellcheck source=/dev/null
  . "$PROJECT_DIR/.env"
fi

# --- Defaults -----------------------------------------------------
KEYCLOAK_URL="${KEYCLOAK_URL:-https://auth.solace.lab}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-solace-lab}"
KEYCLOAK_ADMIN_USER="${KEYCLOAK_ADMIN_USER:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
SAM_CLIENT_ID="${KEYCLOAK_CLIENT_ID:-solace-agent-mesh}"

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

# --- Look up client UUID ------------------------------------------
CLIENT_UUID=$(curl -sf \
  "${BASE}/clients?clientId=${SAM_CLIENT_ID}" \
  -H "Authorization: Bearer ${TOKEN}" \
  | sed -n 's/.*"id":"\([^"]*\)".*/\1/p' | head -1)

if [ -z "$CLIENT_UUID" ]; then
  echo "Client '${SAM_CLIENT_ID}' not found. Nothing to delete."
  exit 0
fi

# --- Delete the client --------------------------------------------
echo "Deleting OIDC client '${SAM_CLIENT_ID}' (${CLIENT_UUID}) ..."
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" -X DELETE \
  "${BASE}/clients/${CLIENT_UUID}" \
  -H "Authorization: Bearer ${TOKEN}")

if [ "$HTTP_CODE" = "204" ]; then
  echo "Client '${SAM_CLIENT_ID}' deleted successfully."
else
  echo "ERROR: Failed to delete client (HTTP ${HTTP_CODE})."
  exit 1
fi
