#!/bin/bash
set -euo pipefail

# =============================================================
# Create the retail demo connectors + agents (SAM v2, CLI-only)
# =============================================================
# Thin wrapper around `sam config plan/apply` with manifest.yaml.
# The manifest reconciles the three postgres connectors and the
# three query-expert agents (with inline instruction-only skills
# and the built-in data_analysis + artifact toolsets) in the
# right order, idempotently. No REST calls, no ID handling.
#
# Agents are created NOT deployed by default: apply runs with
# --no-deploy (config sync only). Deploy in the same run with
# --deploy, or later by re-running with --deploy. The agent files
# declare deploy: true as the desired end state.
#
# NEVER pass --prune to sam config apply here: the platform also
# hosts agents this manifest does not manage (e.g. Orchestrator),
# and --prune would delete them.
#
# Prerequisites: a sam CLI login as a user with agent_builder and
# connector scopes (e.g. the bootstrap admin):
#   sam auth login solace-lab --url https://sam.solace.lab
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

usage() {
  cat <<'USAGE'
Usage:
  ./create.sh              # create/update connectors + agents (no deploy)
  ./create.sh --deploy     # same, and deploy the agents
  ./create.sh --dry-run    # plan only, change nothing
  ./create.sh -h|--help

Optional env (defaults come from manifest.yaml variables):
  RETAIL_DB_USERNAME  DB user for the connectors     (default postgres)
  RETAIL_DB_PASSWORD  DB password for the connectors (default postgres)
USAGE
}

DRY_RUN=0
DEPLOY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --deploy)   DEPLOY=1; shift ;;
    --dry-run)  DRY_RUN=1; shift ;;
    -h|--help)  usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

# --- Load environment variables -----------------------------------
if [ -f "$PROJECT_DIR/.env" ]; then
  # shellcheck source=/dev/null
  . "$PROJECT_DIR/.env"
fi

# --- Resolve the sam CLI (same order as scripts/rbac) --------------
SAM_CLI=""
if [ -n "${SAM_CLI_PATH:-}" ] && [ -x "$SAM_CLI_PATH" ]; then
  SAM_CLI="$SAM_CLI_PATH"
elif command -v sam >/dev/null 2>&1; then
  SAM_CLI="$(command -v sam)"
fi
if [ -z "$SAM_CLI" ]; then
  echo "ERROR: sam CLI not found. Set SAM_CLI_PATH in .env or put" >&2
  echo "'sam' on the PATH (see scripts/rbac/README.md)." >&2
  exit 1
fi
echo "Using sam CLI: $SAM_CLI"

cd "$SCRIPT_DIR"
echo ""
echo "=== sam config plan ==="
if ! "$SAM_CLI" config plan -m manifest.yaml; then
  echo ""
  echo "Plan failed. If this is an authentication error, log in first:"
  echo "  $SAM_CLI auth login solace-lab --url https://sam.solace.lab"
  exit 1
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo ""
  echo "DRY RUN complete - nothing was applied."
  exit 0
fi

echo ""
echo "=== sam config apply ==="
if [ "$DEPLOY" -eq 1 ]; then
  "$SAM_CLI" config apply -m manifest.yaml
  echo ""
  echo "Connectors and agents applied; agents deployed."
else
  "$SAM_CLI" config apply -m manifest.yaml --no-deploy
  echo ""
  echo "Connectors and agents applied (agents NOT deployed)."
  echo "Deploy them with:  ./create.sh --deploy"
fi
