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
#      (or at $SAM_URL)
#   2. A sam CLI login as the bootstrap admin:
#        sam auth login solace-lab --url https://sam.solace.lab
#      (log in as Keycloak demo user sam_admin / sam_admin)
#
# Optional environment (unset = the local lab): SAM_ENV_FILE,
# SAM_HOME, SAM_URL -- see scripts/lib/common.sh.
#
# CLI resolution order (scripts/lib/common.sh): SAM_CLI_PATH from
# .env, `sam` on PATH, else auto-extract from SAM_CLI_TAR into
# scripts/lib/.cache/ (gitignored).
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# --- Shared helpers (env, sam CLI resolution) ----------------------
# shellcheck source=../lib/common.sh
. "$PROJECT_DIR/scripts/lib/common.sh"
load_env "$PROJECT_DIR" "${SAM_ENV_FILE:-$PROJECT_DIR/.env}"
sam_target_check "$PROJECT_DIR" || exit 1
resolve_sam_cli

# Messages only (the commands target SAM_URL via common.sh).
SAM_BASE="${SAM_BASE:-$(sam_base_url)}"

# --- Plan and apply -----------------------------------------------
cd "$SCRIPT_DIR"
echo ""
echo "=== sam config plan ==="
if ! sam_cli_config plan -m manifest.yaml; then
  echo ""
  echo "Plan failed. If this is an authentication error, log in first:"
  if [ -n "${SAM_HOME:-}" ]; then
    echo "  $(sam_login_cmd)"
  else
    echo "  $SAM_CLI auth login solace-lab --url $SAM_BASE"
  fi
  echo "(as Keycloak demo user sam_admin)"
  exit 1
fi

echo ""
echo "=== sam config apply ==="
sam_cli_config apply -m manifest.yaml

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
sam_auth_token || true
SAM_USER_ID=$(sam_cli_api /api/v1/platform/rbac/roles 2>/dev/null \
  | python3 -c "
import sys, json
raw = ''.join(l for l in sys.stdin if l.lstrip().startswith(('{','[')))
d = json.loads(raw)
rows = d.get('data') if isinstance(d, dict) else d
print(next((r['id'] for r in rows or [] if r.get('name') == 'sam_user'), ''))" \
  2>/dev/null || true)
if [ -n "${SAM_USER_ID:-}" ] && printf '{"roleIds": ["%s"]}' "$SAM_USER_ID" \
     | sam_cli_api -X PUT /api/v1/platform/rbac/defaultRoles --input - >/dev/null 2>&1; then
  echo "Default roles set to [sam_user] ($SAM_USER_ID)."
else
  echo "WARNING: could not set default roles automatically."
  echo "Current value:"
  sam_cli_api /api/v1/platform/rbac/defaultRoles 2>/dev/null || true
  echo "Set manually with the sam_user role id:"
  echo "  echo '{\"roleIds\": [\"<id>\"]}' | $SAM_CLI api -X PUT /api/v1/platform/rbac/defaultRoles --input -"
fi

echo ""
echo "RBAC configuration applied."
