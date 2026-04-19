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

GROUPS="admin user viewer data_engineer power_user"
USERS="viewer data_engineer power_user"

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
  exit 1
fi

BASE="${KEYCLOAK_URL}/admin/realms/${KEYCLOAK_REALM}"

# --- Helper: find group UUID by name ------------------------------
get_group_id() {
  NAME="$1"
  curl -sf "${BASE}/groups?search=${NAME}&exact=true" \
    -H "Authorization: Bearer ${TOKEN}" \
    | sed -n 's/.*"id":"\([^"]*\)","name":"'"${NAME}"'".*/\1/p' \
    | head -1
}

# --- Helper: find user UUID by username ---------------------------
get_user_id() {
  NAME="$1"
  curl -sf "${BASE}/users?username=${NAME}&exact=true" \
    -H "Authorization: Bearer ${TOKEN}" \
    | sed -n 's/.*"id":"\([^"]*\)".*/\1/p' \
    | head -1
}

# --- Create groups -----------------------------------------------
for GROUP in $GROUPS; do
  EXISTING=$(get_group_id "$GROUP")
  if [ -n "$EXISTING" ]; then
    echo "Group '${GROUP}' already exists."
    continue
  fi

  echo "Creating group '${GROUP}' ..."
  curl -sf -o /dev/null -X POST "${BASE}/groups" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"${GROUP}\"}"
done

# --- Create users and assign groups -------------------------------
for USER in $USERS; do
  EXISTING=$(get_user_id "$USER")
  if [ -n "$EXISTING" ]; then
    echo "User '${USER}' already exists."
    USER_UUID="$EXISTING"
  else
    echo "Creating user '${USER}' ..."
    curl -sf -o /dev/null -X POST "${BASE}/users" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/json" \
      -d "{
        \"username\": \"${USER}\",
        \"email\": \"${USER}@solace.lab\",
        \"emailVerified\": true,
        \"enabled\": true,
        \"credentials\": [{
          \"type\": \"password\",
          \"value\": \"${USER}\",
          \"temporary\": false
        }]
      }"
    USER_UUID=$(get_user_id "$USER")
  fi

  if [ -z "$USER_UUID" ]; then
    echo "ERROR: Could not resolve UUID for user '${USER}'."
    continue
  fi

  GROUP_UUID=$(get_group_id "$USER")
  if [ -z "$GROUP_UUID" ]; then
    echo "ERROR: Group '${USER}' not found."
    continue
  fi

  echo "Assigning user '${USER}' to group '${USER}' ..."
  curl -sf -o /dev/null -X PUT \
    "${BASE}/users/${USER_UUID}/groups/${GROUP_UUID}" \
    -H "Authorization: Bearer ${TOKEN}"
done

# --- Assign existing admin/user users to their groups -------------
for NAME in admin user; do
  USER_UUID=$(get_user_id "$NAME")
  if [ -z "$USER_UUID" ]; then
    echo "User '${NAME}' not found in realm, skipping."
    continue
  fi

  GROUP_UUID=$(get_group_id "$NAME")
  if [ -z "$GROUP_UUID" ]; then
    echo "ERROR: Group '${NAME}' not found."
    continue
  fi

  echo "Assigning existing user '${NAME}' to group '${NAME}' ..."
  curl -sf -o /dev/null -X PUT \
    "${BASE}/users/${USER_UUID}/groups/${GROUP_UUID}" \
    -H "Authorization: Bearer ${TOKEN}"
done

echo ""
echo "Keycloak users and groups setup complete."
