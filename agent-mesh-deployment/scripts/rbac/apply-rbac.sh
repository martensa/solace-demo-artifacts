#!/bin/bash
set -euo pipefail

# =============================================================
# Apply the declarative RBAC config to the SAM v2 platform
# =============================================================
# Applies manifest.yaml (roles + Keycloak group claim mappings)
# via `sam config apply`, then sets the platform default roles.
#
# Prerequisites:
#   1. SAM deployed and reachable at https://sam.solace.lab
#   2. A sam CLI login as the bootstrap admin:
#        sam auth login solace-lab --url https://sam.solace.lab
#      (log in as Keycloak demo user sam_admin / sam_admin)
#
# CLI resolution order: SAM_CLI_PATH from .env, `sam` on PATH,
# else auto-extract from SAM_CLI_TAR into .cache/ (gitignored).
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

SAM_BASE="${SAM_BASE:-https://sam.solace.lab}"

# --- Load environment variables -----------------------------------
if [ -f "$PROJECT_DIR/.env" ]; then
  # shellcheck source=/dev/null
  . "$PROJECT_DIR/.env"
fi

# --- Resolve the sam CLI ------------------------------------------
SAM_CLI=""
if [ -n "${SAM_CLI_PATH:-}" ] && [ -x "$SAM_CLI_PATH" ]; then
  SAM_CLI="$SAM_CLI_PATH"
elif command -v sam >/dev/null 2>&1; then
  SAM_CLI="$(command -v sam)"
elif [ -n "${SAM_CLI_TAR:-}" ] && [ -f "$SAM_CLI_TAR" ]; then
  echo "Extracting sam CLI from $SAM_CLI_TAR ..."
  mkdir -p "$SCRIPT_DIR/.cache"
  tar -xzf "$SAM_CLI_TAR" -C "$SCRIPT_DIR/.cache" sam
  chmod +x "$SCRIPT_DIR/.cache/sam"
  SAM_CLI="$SCRIPT_DIR/.cache/sam"
fi
if [ -z "$SAM_CLI" ]; then
  echo "ERROR: sam CLI not found. Set SAM_CLI_PATH or SAM_CLI_TAR in"
  echo ".env, or put 'sam' on the PATH. The CLI ships in the SAM"
  echo "delivery package as solace-agent-mesh-<ver>-cli-<os>-<arch>.tar.gz"
  exit 1
fi
echo "Using sam CLI: $SAM_CLI"

# --- Plan and apply -----------------------------------------------
cd "$SCRIPT_DIR"
echo ""
echo "=== sam config plan ==="
if ! "$SAM_CLI" config plan -m manifest.yaml; then
  echo ""
  echo "Plan failed. If this is an authentication error, log in first:"
  echo "  $SAM_CLI auth login solace-lab --url $SAM_BASE"
  echo "(as Keycloak demo user sam_admin)"
  exit 1
fi

echo ""
echo "=== sam config apply ==="
"$SAM_CLI" config apply -m manifest.yaml

# --- Default roles (fallback for unmapped users) -------------------
# v1 parity: defaultRoles [sam_user]. There is no declarative kind
# for default roles; set them via the platform REST API
# (PUT /api/v1/platform/rbac/defaultRoles, payload {"roleIds": [..]}).
# Only DB-managed roles are accepted, so this runs after the apply
# above created the sam_user role.
#
# Note (CLI 2.225.14, Early Access): `sam api` does not attach the
# cached OAuth token itself -- export it as SAM_AUTH_TOKEN from the
# login cache written by `sam auth login solace-lab`.
echo ""
echo "=== default roles -> [sam_user] ==="
AUTH_CACHE="$HOME/Library/Application Support/sam/auth/solace-lab.json"
if [ -f "$AUTH_CACHE" ]; then
  SAM_AUTH_TOKEN=$(python3 -c \
    "import json;print(json.load(open('$AUTH_CACHE'))['sam_access_token'])")
  export SAM_AUTH_TOKEN
fi
SAM_USER_ID=$("$SAM_CLI" api /api/v1/platform/rbac/roles 2>/dev/null \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
rows = d.get('data') if isinstance(d, dict) else d
print(next((r['id'] for r in rows or [] if r.get('name') == 'sam_user'), ''))" \
  2>/dev/null || true)
if [ -n "${SAM_USER_ID:-}" ] && printf '{"roleIds": ["%s"]}' "$SAM_USER_ID" \
     | "$SAM_CLI" api -X PUT /api/v1/platform/rbac/defaultRoles --input - >/dev/null 2>&1; then
  echo "Default roles set to [sam_user] ($SAM_USER_ID)."
else
  echo "WARNING: could not set default roles automatically."
  echo "Current value:"
  "$SAM_CLI" api /api/v1/platform/rbac/defaultRoles 2>/dev/null || true
  echo "Set manually with the sam_user role id:"
  echo "  echo '{\"roleIds\": [\"<id>\"]}' | $SAM_CLI api -X PUT /api/v1/platform/rbac/defaultRoles --input -"
fi

echo ""
echo "RBAC configuration applied."
