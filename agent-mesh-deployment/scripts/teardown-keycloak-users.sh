#!/bin/bash
set -euo pipefail

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

SAM_GROUPS="admin user viewer data_engineer power_user"
SAM_USERS="viewer data_engineer power_user"

# --- Check dependencies -------------------------------------------
if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required but not installed."
  exit 1
fi

# --- Obtain admin token -------------------------------------------
echo "Obtaining Keycloak admin token ..."
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

# --- Delete users -------------------------------------------------
for USER in $SAM_USERS; do
  USER_UUID=$(curl -sk "${BASE}/users?username=${USER}&exact=true" \
    -H "Authorization: Bearer ${TOKEN}" \
    | jq -r --arg n "$USER" '.[] | select(.username==$n) | .id' \
    | head -1)

  if [ -z "$USER_UUID" ]; then
    echo "User '${USER}' not found, skipping."
    continue
  fi

  echo "Deleting user '${USER}' ..."
  curl -sk -o /dev/null -X DELETE \
    "${BASE}/users/${USER_UUID}" \
    -H "Authorization: Bearer ${TOKEN}"
done

# --- Delete groups ------------------------------------------------
# Also removes group memberships of pre-existing users (admin, user)
for GROUP in $SAM_GROUPS; do
  GROUP_UUID=$(curl -sk "${BASE}/groups?search=${GROUP}&exact=true" \
    -H "Authorization: Bearer ${TOKEN}" \
    | jq -r --arg n "$GROUP" '.[] | select(.name==$n) | .id' \
    | head -1)

  if [ -z "$GROUP_UUID" ]; then
    echo "Group '${GROUP}' not found, skipping."
    continue
  fi

  echo "Deleting group '${GROUP}' ..."
  curl -sk -o /dev/null -X DELETE \
    "${BASE}/groups/${GROUP_UUID}" \
    -H "Authorization: Bearer ${TOKEN}"
done

echo ""
echo "Keycloak users and groups teardown complete."
