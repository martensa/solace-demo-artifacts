#!/bin/bash
# G0-08a: read-only SAM API GET with the cached login (no secrets here).
#   ./samapi.sh /api/v1/tasks?pageSize=100
# Re-resolves the token on every call, so a renewed login is picked up.
set -u
cd "$(dirname "$0")/../../../../agent-mesh-deployment" || exit 2
# shellcheck disable=SC1091
source scripts/lib/common.sh >/dev/null 2>&1
load_env "$PWD" >/dev/null 2>&1
resolve_sam_cli >/dev/null 2>&1
sam_auth_token >/dev/null 2>&1
export SAM_AUTH_TOKEN
exec "$SAM_CLI" api --url https://sam.solace.lab "$1"
