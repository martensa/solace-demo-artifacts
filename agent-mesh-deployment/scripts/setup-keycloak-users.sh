#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Optional environment (unset = the local lab, unchanged):
#   SAM_ENV_FILE  env file instead of ../.env
# KEYCLOAK_ADMIN_PASSWORD from the environment is used when the env
# file does not set it (aks_kc passes it that way).
ENV_FILE="${SAM_ENV_FILE:-$PROJECT_DIR/.env}"

# --- Load environment variables -----------------------------------
if [ ! -f "$ENV_FILE" ]; then
  if [ -n "${SAM_ENV_FILE:-}" ]; then
    echo "No env file found: $ENV_FILE"
  else
    echo "No .env file found. Copy .env.example to .env first."
  fi
  exit 1
fi

# shellcheck source=/dev/null
. "$ENV_FILE"

# --- Defaults -----------------------------------------------------
# An explicit env file (AKS) must name its Keycloak and admin
# password itself: never fall back to the lab defaults below.
if [ -n "${SAM_ENV_FILE:-}" ] && [ -z "${KEYCLOAK_URL:-}" ]; then
  echo "ERROR: KEYCLOAK_URL is not set in $ENV_FILE." >&2
  exit 1
fi
if [ -n "${SAM_ENV_FILE:-}" ] && [ -z "${KEYCLOAK_ADMIN_PASSWORD:-}" ]; then
  echo "ERROR: KEYCLOAK_ADMIN_PASSWORD is not set (environment or $ENV_FILE)." >&2
  exit 1
fi
KEYCLOAK_URL="${KEYCLOAK_URL:-https://auth.solace.lab}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-solace-lab}"
KEYCLOAK_ADMIN_USER="${KEYCLOAK_ADMIN_USER:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"

SAM_GROUPS="admin user viewer data_engineer power_user sam_manager"

# Demo users to create. Username equals group name by default
# (see user_to_group below for exceptions). sam_manager (group
# sam_manager) maps to the built-in SAM role of the same name:
# administer everything in SAM except RBAC -- the separation-of-
# duties persona next to the bootstrap admin sam_admin.
SAM_USERS="viewer data_engineer power_user sam_manager sam_admin sam_user"

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
# With SAM_ENV_FILE (a remote Keycloak; aks_kc passes the admin
# password from the Key Vault) neither the password nor the admin
# token ever goes into an argv (visible to ps and process auditing):
# the password reaches curl on stdin, the bearer header through a
# curl config on a file descriptor (kc_curl below). The lab keeps its
# argv as it always was.
echo "Obtaining Keycloak admin token from ${KEYCLOAK_URL} ..."
if [ -n "${SAM_ENV_FILE:-}" ]; then
  TOKEN_RESPONSE=$(printf '%s' "$KEYCLOAK_ADMIN_PASSWORD" | curl -sk -X POST \
    "${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=password" \
    -d "client_id=admin-cli" \
    --data-urlencode "username=${KEYCLOAK_ADMIN_USER}" \
    --data-urlencode "password@-")
else
  TOKEN_RESPONSE=$(curl -sk -X POST \
    "${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=password" \
    -d "client_id=admin-cli" \
    -d "username=${KEYCLOAK_ADMIN_USER}" \
    -d "password=${KEYCLOAK_ADMIN_PASSWORD}")
fi

TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token // empty')

if [ -z "$TOKEN" ]; then
  echo "ERROR: Failed to obtain admin token. Response:"
  echo "$TOKEN_RESPONSE"
  exit 1
fi

BASE="${KEYCLOAK_URL}/admin/realms/${KEYCLOAK_REALM}"

# --- Helper: curl with the admin bearer token ----------------------
# Lab: the header is in the argv, passed by the caller as
# ${AUTH_H[@]} exactly where it always was. Remote (SAM_ENV_FILE):
# AUTH_H is empty and kc_curl reads the header from a curl config on
# a file descriptor (printf is a builtin: no argv anywhere).
if [ -n "${SAM_ENV_FILE:-}" ]; then
  case "$TOKEN" in
    *[!A-Za-z0-9._~+/=-]*)
      echo "ERROR: the admin token has unexpected characters." >&2; exit 1 ;;
  esac
  AUTH_H=()
else
  AUTH_H=(-H "Authorization: Bearer ${TOKEN}")
fi
kc_curl() {
  if [ -n "${SAM_ENV_FILE:-}" ]; then
    curl --config <(printf 'header = "Authorization: Bearer %s"\n' "$TOKEN") "$@"
  else
    curl "$@"
  fi
}

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
  kc_curl -sk "${BASE}/groups?search=${NAME}&exact=true" \
    ${AUTH_H[@]+"${AUTH_H[@]}"} \
    | jq -r --arg n "$NAME" '.[] | select(.name==$n) | .id' \
    | head -1
}

# --- Helper: find user UUID by username ---------------------------
get_user_id() {
  NAME="$1"
  kc_curl -sk "${BASE}/users?username=${NAME}&exact=true" \
    ${AUTH_H[@]+"${AUTH_H[@]}"} \
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
  HTTP_CODE=$(kc_curl -sk -o /dev/null -w "%{http_code}" -X POST \
    "${BASE}/groups" \
    ${AUTH_H[@]+"${AUTH_H[@]}"} \
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
    HTTP_CODE=$(kc_curl -sk -o /dev/null -w "%{http_code}" -X POST \
      "${BASE}/users" \
      ${AUTH_H[@]+"${AUTH_H[@]}"} \
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
  kc_curl -sk -o /dev/null -X PUT \
    "${BASE}/users/${USER_UUID}/groups/${GROUP_UUID}" \
    ${AUTH_H[@]+"${AUTH_H[@]}"}
done

# Note: Realm-import accounts ('admin', 'user') are deliberately
# NOT auto-assigned to any SAM group. They stay as pure Keycloak
# realm accounts for identity management. SAM roles are bound
# exclusively to the demo users created above.

echo ""
echo "Keycloak users and groups setup complete."
