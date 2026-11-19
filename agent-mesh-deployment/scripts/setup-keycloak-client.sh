#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Optional environment (all unset = the local lab, unchanged):
#   SAM_ENV_FILE      env file instead of ../.env (read here, and the
#                     client secret is written back into it)
#   SAM_DNS_NAME      SAM host (lab: always sam.solace.lab)
#   SAM_REDIRECT_URI  exact redirect URI instead of the wildcard
#                     https://<SAM_DNS_NAME>/* (AKS:
#                     https://<FQDN>/api/v1/auth/callback)
#   Both count only together with SAM_ENV_FILE.
# With SAM_ENV_FILE set, SAM_DNS_NAME and SAM_REDIRECT_URI are
# required, and an existing client must already carry exactly
# SAM_REDIRECT_URI (otherwise: exit 1, delete it and re-run).
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
if [ -n "${SAM_ENV_FILE:-}" ] && [ -z "${SAM_DNS_NAME:-}" ]; then
  echo "ERROR: SAM_ENV_FILE is set but SAM_DNS_NAME is not." >&2
  exit 1
fi
# A remote client gets exactly one redirect URI, never the lab
# wildcard https://<SAM_DNS_NAME>/*.
if [ -n "${SAM_ENV_FILE:-}" ] && [ -z "${SAM_REDIRECT_URI:-}" ]; then
  echo "ERROR: SAM_ENV_FILE is set but SAM_REDIRECT_URI is not." >&2
  exit 1
fi
KEYCLOAK_URL="${KEYCLOAK_URL:-https://auth.solace.lab}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-solace-lab}"
KEYCLOAK_ADMIN_USER="${KEYCLOAK_ADMIN_USER:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
SAM_CLIENT_ID="${KEYCLOAK_CLIENT_ID:-solace-agent-mesh}"
# The lab keeps its fixed host and wildcard: SAM_DNS_NAME and
# SAM_REDIRECT_URI count only with SAM_ENV_FILE (checked above), so a
# stray value in a lab shell never changes the lab client.
if [ -z "${SAM_ENV_FILE:-}" ]; then
  SAM_DNS_NAME="sam.solace.lab"
  SAM_REDIRECT_URI=""
fi

# Note: The SAM Helm chart computes the redirect URI automatically
# (actual path: /api/v1/auth/callback). In the lab we register
# https://<SAM_DNS_NAME>/* as redirect URI wildcard so any callback
# path issued by SAM is accepted by Keycloak. With SAM_REDIRECT_URI
# set, only that exact URI is registered, and the post-logout
# redirect (otherwise covered by the wildcard) gets its own
# https://<SAM_DNS_NAME>/* entry.
if [ -n "${SAM_REDIRECT_URI:-}" ]; then
  REDIRECT_URIS_JSON="\"${SAM_REDIRECT_URI}\""
  CLIENT_ATTRIBUTES_JSON=",
    \"attributes\": {
      \"post.logout.redirect.uris\": \"https://${SAM_DNS_NAME}/*\"
    }"
else
  REDIRECT_URIS_JSON="\"https://${SAM_DNS_NAME}/*\""
  CLIENT_ATTRIBUTES_JSON=""
fi

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

# --- Helper: find client UUID by clientId -------------------------
get_client_uuid() {
  kc_curl -sk "${BASE}/clients?clientId=${SAM_CLIENT_ID}" \
    ${AUTH_H[@]+"${AUTH_H[@]}"} \
    | jq -r --arg c "$SAM_CLIENT_ID" \
        '.[] | select(.clientId==$c) | .id' \
    | head -1
}

# --- Helper: write the client secret into .env ---------------------
# The secret changes with every client re-creation (stop.sh deletes
# the client), so it is written straight into .env instead of being
# printed for a manual copy -- start.sh reads it from there.
write_secret_to_env() {
  local secret="$1"
  if [ -z "$secret" ]; then
    echo "ERROR: Keycloak returned no client secret." >&2
    exit 1
  fi
  # Rewrites the file in place (an existing file keeps its mode); a
  # file that does not exist yet is created with mode 600.
  KC_SECRET="$secret" python3 - "$ENV_FILE" <<'PY'
import os, sys
path, secret = sys.argv[1], os.environ["KC_SECRET"]
lines = open(path).read().splitlines() if os.path.exists(path) else []
line = "KEYCLOAK_CLIENT_SECRET=" + secret
hits = [i for i, l in enumerate(lines) if l.startswith("KEYCLOAK_CLIENT_SECRET=")]
if hits:
    for i in hits:
        lines[i] = line
else:
    lines.append(line)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    f.write("\n".join(lines) + "\n")
PY
  echo ""
  echo "Client ID:     ${SAM_CLIENT_ID}"
  if [ -n "${SAM_ENV_FILE:-}" ]; then
    echo "Client Secret: written to ${ENV_FILE} as KEYCLOAK_CLIENT_SECRET"
  else
    echo "Client Secret: ${secret:0:4}... (written to .env as KEYCLOAK_CLIENT_SECRET)"
  fi
}

# --- Check if client already exists -------------------------------
CLIENT_UUID=$(get_client_uuid)

if [ -n "$CLIENT_UUID" ]; then
  echo "Client '${SAM_CLIENT_ID}' already exists (${CLIENT_UUID})."
  # A remote client must carry exactly SAM_REDIRECT_URI; an older one
  # (e.g. with the wildcard) is never accepted as is.
  if [ -n "${SAM_ENV_FILE:-}" ]; then
    FOUND_URIS=$(kc_curl -sk "${BASE}/clients/${CLIENT_UUID}" \
      | jq -c '[(.redirectUris // [])[]] | sort') || FOUND_URIS=""
    WANT_URIS=$(jq -cn --arg u "$SAM_REDIRECT_URI" '[$u]')
    if [ "$FOUND_URIS" != "$WANT_URIS" ]; then
      echo "ERROR: client '${SAM_CLIENT_ID}' has the redirect URIs" >&2
      echo "  ${FOUND_URIS:-(unreadable)}, expected exactly ${WANT_URIS}." >&2
      echo "  Delete the client (Keycloak admin REST or console) and" >&2
      echo "  re-run this script." >&2
      exit 1
    fi
  fi
  echo "Fetching client secret ..."
  SECRET=$(kc_curl -sk \
    "${BASE}/clients/${CLIENT_UUID}/client-secret" \
    ${AUTH_H[@]+"${AUTH_H[@]}"} \
    | jq -r '.value // empty')
  write_secret_to_env "$SECRET"
  exit 0
fi

# --- Create the OIDC client --------------------------------------
echo "Creating OIDC client '${SAM_CLIENT_ID}' ..."
HTTP_CODE=$(kc_curl -sk -o /dev/null -w "%{http_code}" -X POST \
  "${BASE}/clients" \
  ${AUTH_H[@]+"${AUTH_H[@]}"} \
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
    \"redirectUris\": [${REDIRECT_URIS_JSON}],
    \"webOrigins\": [\"https://${SAM_DNS_NAME}\"],
    \"defaultClientScopes\": [
      \"openid\", \"email\", \"profile\"
    ]${CLIENT_ATTRIBUTES_JSON}
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
HTTP_CODE=$(kc_curl -sk -o /dev/null -w "%{http_code}" -X POST \
  "${BASE}/clients/${CLIENT_UUID}/protocol-mappers/models" \
  ${AUTH_H[@]+"${AUTH_H[@]}"} \
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
OFFLINE_ACCESS_ID=$(kc_curl -sk "${BASE}/client-scopes" \
  ${AUTH_H[@]+"${AUTH_H[@]}"} \
  | jq -r '.[] | select(.name=="offline_access") | .id')

if [ -n "$OFFLINE_ACCESS_ID" ]; then
  HTTP_CODE=$(kc_curl -sk -o /dev/null -w "%{http_code}" -X PUT \
    "${BASE}/clients/${CLIENT_UUID}/optional-client-scopes/${OFFLINE_ACCESS_ID}" \
    ${AUTH_H[@]+"${AUTH_H[@]}"})
  if [ "$HTTP_CODE" != "204" ]; then
    echo "WARNING: adding offline_access scope failed (HTTP ${HTTP_CODE})."
    echo "Refresh tokens may be unavailable to SAM."
  fi
else
  echo "WARNING: offline_access scope not found in realm."
fi

# --- Fetch client secret ------------------------------------------
SECRET=$(kc_curl -sk \
  "${BASE}/clients/${CLIENT_UUID}/client-secret" \
  ${AUTH_H[@]+"${AUTH_H[@]}"} \
  | jq -r '.value // empty')

echo ""
echo "OIDC client created successfully."
write_secret_to_env "$SECRET"
