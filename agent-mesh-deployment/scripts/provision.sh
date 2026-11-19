#!/bin/bash
set -uo pipefail

# =============================================================
# provision.sh -- the DB-managed platform content, in order
# =============================================================
# A fresh install (start.sh after stop.sh, or an upgrade) starts
# with an empty platform database. This re-creates everything this
# deployment owns there, in the order that works:
#
#   1. RBAC        roles, Keycloak claim mappings, default roles
#   2. Models      the extra aliases (workflow, reasoning, coding,
#                  expert, fast, google gemini) + upstream probe
#   3. max_tokens  on the seeded general/planning/report_gen
#                  (one awe restart, only if something changed)
#   4. Pricing     token rates on fast, workflow and planning
#                  (token governance treats unpriced as free)
#   5. Entrypoint  developer-mcp
#
# All five steps are idempotent, so a re-run is safe and cheap.
# Demos are NOT part of this -- install them afterwards with their
# own install.sh.
#
# Every step talks to the platform through the sam CLI and needs a
# login as the bootstrap admin (Keycloak user sam_admin), which
# can only exist once the platform is up:
#
#   ./provision.sh           # needs an existing login
#   ./provision.sh --login   # run `sam auth login` first (browser)
#                            # when no login cache exists
#
# start.sh calls this after the pods are ready (--login when it
# runs in a terminal).
#
# Optional environment (unset = the local lab): SAM_ENV_FILE (env
# file instead of ../.env), SAM_HOME (sam CLI home and login cache),
# SAM_URL (platform URL; every sam config/api call of the steps
# targets it). See scripts/lib/common.sh. For AKS, aks_sam in
# gebit-price-agent-demo/infra/aks/aks.sh sets all three.
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

LOGIN=0
case "${1:-}" in
  --login)   LOGIN=1 ;;
  -h|--help) grep '^#   \./' "$0" | sed 's/^#   //'; exit 0 ;;
  "")        ;;
  *)         echo "Unknown argument: $1" >&2; exit 1 ;;
esac

# shellcheck source=lib/common.sh
. "$PROJECT_DIR/scripts/lib/common.sh"
load_env "$PROJECT_DIR" "${SAM_ENV_FILE:-$PROJECT_DIR/.env}" || exit 1
sam_target_check "$PROJECT_DIR" || exit 1
resolve_sam_cli || exit 1
# Login URL and messages only; the steps read SAM_URL from the
# environment themselves (unset in the lab).
PLATFORM_URL="$(sam_base_url)"

# --- Login ----------------------------------------------------------
if [ ! -f "$(sam_auth_cache_path)" ]; then
  if [ "$LOGIN" -eq 1 ]; then
    echo "No sam CLI login yet. Opening the browser -- log in as"
    echo "Keycloak user sam_admin ..."
    sam_cli_run auth login solace-lab --url "$PLATFORM_URL" || {
      echo "ERROR: sam auth login failed." >&2; exit 1; }
  else
    echo "ERROR: no sam CLI login. Either run" >&2
    echo "  $(sam_login_cmd)" >&2
    echo "(as sam_admin) and re-run, or run: $0 --login" >&2
    exit 1
  fi
fi

# --- Steps ----------------------------------------------------------
RESULTS=()
FAILED=0
run_step() { # <label> <fatal:0|1> <command...>
  local label="$1" fatal="$2" rc
  shift 2
  echo ""
  echo "=== $label ==="
  "$@"
  rc=$?
  case "$rc" in
    0) RESULTS+=("  OK    $label") ;;
    2) RESULTS+=("  WARN  $label (exit 2, see above)") ;;
    *) RESULTS+=("  FAIL  $label (exit $rc)"); FAILED=1
       if [ "$fatal" -eq 1 ]; then
         echo "" >&2
         echo "ERROR: $label failed -- stopping. If this is an auth" >&2
         echo "error, re-login and re-run:" >&2
         echo "  $(sam_login_cmd)" >&2
         printf '%s\n' "${RESULTS[@]}"
         exit 1
       fi ;;
  esac
}

# RBAC first: it is also the auth smoke test, so a bad login stops
# here instead of failing five times.
run_step "RBAC"       1 "$SCRIPT_DIR/rbac/apply-rbac.sh"
run_step "Models"     0 "$SCRIPT_DIR/models/apply-models.sh"
run_step "max_tokens" 0 "$SCRIPT_DIR/models/set-max-tokens.sh"
run_step "Pricing"    0 "$SCRIPT_DIR/models/set-pricing.sh"
run_step "Entrypoint" 0 "$SCRIPT_DIR/entrypoints/apply-entrypoints.sh"

echo ""
echo "Provisioning summary:"
printf '%s\n' "${RESULTS[@]}"
exit "$FAILED"
