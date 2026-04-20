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

SAM_GROUPS="admin user viewer data_engineer power_user"

# Demo users to create. Username equals group name by default
# (see user_to_group below for exceptions).
SAM_USERS="viewer data_engineer power_user sam_admin sam_user"

# Map a demo user to its Keycloak group.
# Defaults to the username; dedicated 'sam_admin' and 'sam_user'
# demo accounts map to the 'admin' and 'user' groups, which in
# turn bind to the built-in sam_admin and sam_user SAM roles.
user_to_group() {
  case "$1" in
    sam_admin) echo "admin" ;;
    sam_user)  echo "user" ;;
    *) echo "$1" ;;
  esac
}

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

# --- Helper: capitalize underscore-separated username -------------
#   power_user    -> Power_User
#   data_engineer -> Data_Engineer
#   viewer        -> Viewer
capitalize_username() {
  echo "$1" | awk -F'_' '{
    for (i = 1; i <= NF; i++) {
      $i = toupper(substr($i, 1, 1)) tolower(substr($i, 2))
    }
    print
  }' OFS='_'
}

# --- Helper: find group UUID by name ------------------------------
get_group_id() {
  NAME="$1"
  curl -sk "${BASE}/groups?search=${NAME}&exact=true" \
    -H "Authorization: Bearer ${TOKEN}" \
    | jq -r --arg n "$NAME" '.[] | select(.name==$n) | .id' \
    | head -1
}

# --- Helper: find user UUID by username ---------------------------
get_user_id() {
  NAME="$1"
  curl -sk "${BASE}/users?username=${NAME}&exact=true" \
    -H "Authorization: Bearer ${TOKEN}" \
    | jq -r --arg n "$NAME" '.[] | select(.username==$n) | .id' \
    | head -1
}

# --- Create groups -----------------------------------------------
for GROUP in $SAM_GROUPS; do
  EXISTING=$(get_group_id "$GROUP")
  if [ -n "$EXISTING" ]; then
    echo "Group '${GROUP}' already exists (${EXISTING})."
    continue
  fi

  echo "Creating group '${GROUP}' ..."
  HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" -X POST \
    "${BASE}/groups" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"${GROUP}\"}")

  if [ "$HTTP_CODE" != "201" ]; then
    echo "ERROR: Failed to create group '${GROUP}' (HTTP ${HTTP_CODE})."
    exit 1
  fi
done

# --- Create users and assign groups -------------------------------
for USER in $SAM_USERS; do
  FIRST_NAME=$(capitalize_username "$USER")
  LAST_NAME="Solace Lab"

  EXISTING=$(get_user_id "$USER")
  if [ -n "$EXISTING" ]; then
    echo "User '${USER}' already exists (${EXISTING})."
    USER_UUID="$EXISTING"
  else
    echo "Creating user '${USER}' ..."
    HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" -X POST \
      "${BASE}/users" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/json" \
      -d "{
        \"username\": \"${USER}\",
        \"email\": \"${USER}@solace.lab\",
        \"firstName\": \"${FIRST_NAME}\",
        \"lastName\": \"${LAST_NAME}\",
        \"emailVerified\": true,
        \"enabled\": true,
        \"credentials\": [{
          \"type\": \"password\",
          \"value\": \"${USER}\",
          \"temporary\": false
        }]
      }")

    if [ "$HTTP_CODE" != "201" ]; then
      echo "ERROR: Failed to create user '${USER}' (HTTP ${HTTP_CODE})."
      exit 1
    fi
    USER_UUID=$(get_user_id "$USER")
  fi

  if [ -z "$USER_UUID" ]; then
    echo "ERROR: Could not resolve UUID for user '${USER}'."
    exit 1
  fi

  GROUP_NAME=$(user_to_group "$USER")
  GROUP_UUID=$(get_group_id "$GROUP_NAME")
  if [ -z "$GROUP_UUID" ]; then
    echo "ERROR: Group '${GROUP_NAME}' not found."
    exit 1
  fi

  echo "Assigning user '${USER}' to group '${GROUP_NAME}' ..."
  curl -sk -o /dev/null -X PUT \
    "${BASE}/users/${USER_UUID}/groups/${GROUP_UUID}" \
    -H "Authorization: Bearer ${TOKEN}"
done

# Note: Realm-import accounts ('admin', 'user') are deliberately
# NOT auto-assigned to any SAM group. They stay as pure Keycloak
# realm accounts for identity management. SAM roles are bound
# exclusively to the demo users created above.

echo ""
echo "Keycloak users and groups setup complete."
