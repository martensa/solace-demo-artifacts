#!/bin/bash
# =============================================================
# common.sh -- shared helpers for the sam-CLI based scripts
# (agents/create.sh, rbac/apply-rbac.sh, models/set-max-tokens.sh)
# =============================================================
# Source this file; do not execute it. Provides:
#   load_env  <project_dir>   source .env with export (set -a)
#   resolve_sam_cli           sets SAM_CLI (path to the sam binary)
#   sam_auth_token            exports SAM_AUTH_TOKEN from the CLI
#                             login cache (clear error if missing)
#
# CLI resolution order: SAM_CLI_PATH from .env, `sam` on PATH,
# else auto-extract from SAM_CLI_TAR into scripts/lib/.cache/
# (gitignored).
#
# Note: the login cache path is the macOS location used by the
# sam CLI; this lab is macOS-only.

COMMON_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAM_AUTH_CACHE="$HOME/Library/Application Support/sam/auth/solace-lab.json"

load_env() {
  local project_dir="$1"
  if [ -f "$project_dir/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    . "$project_dir/.env"
    set +a
  fi
}

resolve_sam_cli() {
  SAM_CLI=""
  if [ -n "${SAM_CLI_PATH:-}" ] && [ -x "$SAM_CLI_PATH" ]; then
    SAM_CLI="$SAM_CLI_PATH"
  elif command -v sam >/dev/null 2>&1; then
    SAM_CLI="$(command -v sam)"
  elif [ -n "${SAM_CLI_TAR:-}" ] && [ -f "$SAM_CLI_TAR" ]; then
    echo "Extracting sam CLI from $SAM_CLI_TAR ..." >&2
    mkdir -p "$COMMON_LIB_DIR/.cache"
    tar -xzf "$SAM_CLI_TAR" -C "$COMMON_LIB_DIR/.cache" sam
    chmod +x "$COMMON_LIB_DIR/.cache/sam"
    SAM_CLI="$COMMON_LIB_DIR/.cache/sam"
  fi
  if [ -z "$SAM_CLI" ]; then
    echo "ERROR: sam CLI not found. Set SAM_CLI_PATH or SAM_CLI_TAR in" >&2
    echo ".env, or put 'sam' on the PATH. The CLI ships in the SAM" >&2
    echo "delivery package as solace-agent-mesh-<ver>-cli-<os>-<arch>.tar.gz" >&2
    return 1
  fi
  echo "Using sam CLI: $SAM_CLI" >&2
}

sam_auth_token() {
  if [ ! -f "$SAM_AUTH_CACHE" ]; then
    echo "ERROR: no sam CLI login cache. Log in first:" >&2
    echo "  ${SAM_CLI:-sam} auth login solace-lab --url https://sam.solace.lab" >&2
    return 1
  fi
  if ! SAM_AUTH_TOKEN=$(python3 -c \
      "import json;print(json.load(open('$SAM_AUTH_CACHE'))['sam_access_token'])" \
      2>/dev/null); then
    echo "ERROR: could not read the sam login cache ($SAM_AUTH_CACHE)." >&2
    echo "Re-login: ${SAM_CLI:-sam} auth login solace-lab --url https://sam.solace.lab" >&2
    return 1
  fi
  export SAM_AUTH_TOKEN
}
