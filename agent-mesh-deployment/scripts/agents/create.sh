#!/bin/bash
set -euo pipefail

# =============================================================
# Create the retail demo connectors + agents (SAM v2, CLI-only)
# =============================================================
# Thin wrapper around `sam config plan/apply` with manifest.yaml.
# The manifest reconciles the retail demo end to end -- postgres
# connectors, schema skill bundles, the query-expert agents, the
# Retail 360 Reporter, the retail-360-report workflow and the MCP
# entrypoint -- in the right order, idempotently. No REST calls,
# no ID handling.
#
# Resources are created NOT deployed by default: apply runs with
# --no-deploy (config sync only). Deploy with --deploy. CAUTION
# (2.225.14): the deploy phase only fires for resources whose
# config CHANGED in that apply -- re-running --deploy over an
# unchanged, undeployed resource is a silent no-op. To deploy it,
# bump any config field (e.g. the workflow appConfig version) and
# re-run with --deploy.
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

# --- Shared helpers (env, sam CLI resolution) ----------------------
# shellcheck source=../lib/common.sh
. "$PROJECT_DIR/scripts/lib/common.sh"
load_env "$PROJECT_DIR"
resolve_sam_cli

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
