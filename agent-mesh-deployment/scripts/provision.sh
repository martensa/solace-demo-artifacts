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
#   4. Entrypoint  developer-mcp
#
# All four steps are idempotent, so a re-run is safe and cheap.
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
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SAM_URL="https://sam.solace.lab"

LOGIN=0
case "${1:-}" in
  --login)   LOGIN=1 ;;
  -h|--help) grep '^#   \./' "$0" | sed 's/^#   //'; exit 0 ;;
  "")        ;;
  *)         echo "Unknown argument: $1" >&2; exit 1 ;;
esac

# shellcheck source=lib/common.sh
. "$PROJECT_DIR/scripts/lib/common.sh"
load_env "$PROJECT_DIR"
resolve_sam_cli || exit 1

# --- Login ----------------------------------------------------------
if [ ! -f "$SAM_AUTH_CACHE" ]; then
  if [ "$LOGIN" -eq 1 ]; then
    echo "No sam CLI login yet. Opening the browser -- log in as"
    echo "Keycloak user sam_admin ..."
    "$SAM_CLI" auth login solace-lab --url "$SAM_URL" || {
      echo "ERROR: sam auth login failed." >&2; exit 1; }
  else
    echo "ERROR: no sam CLI login. Either run" >&2
    echo "  $SAM_CLI auth login solace-lab --url $SAM_URL" >&2
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
         echo "  $SAM_CLI auth login solace-lab --url $SAM_URL" >&2
         printf '%s\n' "${RESULTS[@]}"
         exit 1
       fi ;;
  esac
}

# RBAC first: it is also the auth smoke test, so a bad login stops
# here instead of failing four times.
run_step "RBAC"       1 "$SCRIPT_DIR/rbac/apply-rbac.sh"
run_step "Models"     0 "$SCRIPT_DIR/models/apply-models.sh"
run_step "max_tokens" 0 "$SCRIPT_DIR/models/set-max-tokens.sh"
run_step "Entrypoint" 0 "$SCRIPT_DIR/entrypoints/apply-entrypoints.sh"

echo ""
echo "Provisioning summary:"
printf '%s\n' "${RESULTS[@]}"
exit "$FAILED"
