#!/bin/bash
set -euo pipefail

# =============================================================
# apply-entrypoints.sh -- create/update the platform-level
# entrypoints (developer-mcp) declaratively.
# =============================================================
# Idempotent: `sam config apply` creates or updates; re-running
# is safe. Called by start.sh after the models (one-click
# deployment) and usable standalone.
#
# NOTE: a config CHANGE redeploys the entrypoint, which
# invalidates its in-memory minted MCP tokens -- connected
# clients (Claude Code, SAM desktop app) re-auth via refresh
# token automatically.
#
# Auth: needs a sam CLI login (browser flow):
#   sam auth login solace-lab --url https://sam.solace.lab
#
#   ./apply-entrypoints.sh           # apply + probe /gw/dev
#   ./apply-entrypoints.sh --probe-only
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

PROBE_ONLY=0
case "${1:-}" in
  --probe-only) PROBE_ONLY=1 ;;
  -h|--help)    grep '^#   \./' "$0" | sed 's/^#   //'; exit 0 ;;
  "")           ;;
  *)            echo "Unknown argument: $1" >&2; exit 1 ;;
esac

# --- Shared helpers (env, sam CLI) ---------------------------------
# shellcheck source=../lib/common.sh
. "$PROJECT_DIR/scripts/lib/common.sh"
load_env "$PROJECT_DIR"

if [ "$PROBE_ONLY" -eq 0 ]; then
  resolve_sam_cli
  echo "Applying platform entrypoints (developer-mcp) ..."
  (cd "$SCRIPT_DIR" && "$SAM_CLI" config apply)
fi

# --- Probe: /gw/dev must answer (401 = up, auth challenge) ----------
CODE=$(curl -sk -m 10 -o /dev/null -w "%{http_code}" \
  https://sam.solace.lab/gw/dev/ || true)
case "$CODE" in
  401|200|405|406)
    echo "developer-mcp endpoint up (HTTP $CODE at /gw/dev/)." ;;
  *)
    echo "WARNING: /gw/dev/ answered HTTP ${CODE:-none} -- the" >&2
    echo "MCP entrypoint may not be deployed yet." >&2
    exit 2 ;;
esac
