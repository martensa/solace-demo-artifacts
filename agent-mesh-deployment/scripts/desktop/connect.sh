#!/bin/bash
set -euo pipefail

# =============================================================
# Connect the SAM desktop app to the local K8s deployment
# =============================================================
# Applies manifest.yaml against the desktop app's local platform
# (http://localhost:8800, no auth):
#   - model 'general' -> lab LiteLLM proxy (key from repo .env)
#   - MCP connector 'SAM K8s Mesh' -> https://sam.solace.lab/gw/dev
#   - attaches the connector to the desktop Orchestrator
#
# Prerequisites: the desktop app is running (open -a "Solace
# Agent Mesh") and the K8s deployment is up. On first tool use
# the app prompts for the Keycloak OAuth login (e.g. sam_admin).
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# --- Shared helpers (env, sam CLI resolution) ----------------------
# shellcheck source=../lib/common.sh
. "$PROJECT_DIR/scripts/lib/common.sh"
load_env "$PROJECT_DIR"
resolve_sam_cli

if ! curl -s --max-time 3 http://localhost:8800/api/v1/platform/health >/dev/null; then
  echo "ERROR: desktop app platform not reachable on :8800." >&2
  echo "Start it first:  open -a \"Solace Agent Mesh\"" >&2
  exit 1
fi

cd "$SCRIPT_DIR"
echo "=== sam config plan ==="
"$SAM_CLI" config plan -m manifest.yaml

echo ""
echo "=== sam config apply ==="
"$SAM_CLI" config apply -m manifest.yaml

echo ""
echo "Desktop app connected to the K8s mesh (MCP entrypoint)."
echo "First K8s tool call triggers the Keycloak OAuth login in the"
echo "app (log in e.g. as sam_admin or power_user)."
