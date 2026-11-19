#!/bin/bash
# =============================================================
# common.sh -- shared helpers for the sam-CLI based scripts
# (rbac/apply-rbac.sh, models/*, entrypoints/apply-entrypoints.sh
# and the demo install/uninstall scripts in ../../../sam-*-demo/)
# =============================================================
# Source this file; do not execute it. Provides:
#   load_env  <project_dir> [file]
#                             source <file> (default
#                             <project_dir>/.env) with export
#                             (set -a)
#   resolve_sam_cli           sets SAM_CLI (path to the sam binary)
#   sam_auth_cache_path       prints the CLI login cache path
#   sam_auth_token            exports SAM_AUTH_TOKEN from the CLI
#                             login cache (clear error if missing)
#   sam_base_url              prints the platform URL (SAM_URL,
#                             default https://sam.solace.lab)
#   sam_cli_run <args>        "$SAM_CLI" <args>; with SAM_HOME set
#                             as HOME=$SAM_HOME (remote login cache)
#   sam_login_cmd             prints the login command for messages
#   sam_cli_config <args>     sam_cli_run config <args>, plus
#                             --url "$SAM_URL" --no-dotenv when
#                             SAM_URL is set
#   sam_cli_api <args>        sam_cli_run api <args>, plus
#                             --url "$SAM_URL" when SAM_URL is set
#   sam_target_check <project_dir>
#                             refuses a partial or lab-mixed set of
#                             the three target variables below (the
#                             agent-mesh-deployment scripts call it
#                             right after load_env); on a remote
#                             target it also unsets SAM_AUTH_TOKEN
#                             and SAM_PLATFORM_TOKEN
#
# Optional environment (all unset = the local lab, unchanged):
#   SAM_ENV_FILE  env file the agent-mesh-deployment scripts load
#                 instead of .env (they pass it to load_env; the
#                 demos never do)
#   SAM_HOME      HOME the sam CLI runs with for that platform:
#                 sam 2.542.1 keeps its OAuth login cache under
#                 $HOME/Library/Application Support/sam/auth and
#                 ignores SAM_HOME and --sam-home for it, so
#                 sam_cli_run sets HOME=$SAM_HOME and the cache is
#                 $SAM_HOME/Library/Application Support/sam/auth/
#                 solace-lab.json
#   SAM_URL       platform URL, e.g. https://<AKS FQDN>; every
#                 `sam config` and `sam api` call targets it
#                 explicitly instead of the manifests' target.url
#                 (https://sam.solace.lab) or the cached login
# The three switch the target together: none = the lab, all three =
# a remote platform (aks_sam in gebit-price-agent-demo/infra/aks/
# aks.sh sets them); sam_target_check enforces that.
#
# CLI resolution order: SAM_CLI_PATH from .env, `sam` on PATH,
# else auto-extract from SAM_CLI_TAR into scripts/lib/.cache/
# (gitignored).
#
# Note: the default login cache path is the macOS location used by
# the sam CLI; this lab is macOS-only.

COMMON_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Login cache of `sam auth login solace-lab`. Evaluated at call time,
# so a SAM_HOME exported after sourcing this file still counts. The
# CLI derives it from HOME only (see SAM_HOME above).
sam_auth_cache_path() {
  printf '%s/Library/Application Support/sam/auth/solace-lab.json\n' \
    "${SAM_HOME:-$HOME}"
}
# Kept for compatibility with callers that read the variable; it
# reflects SAM_HOME at source time only -- prefer the function.
SAM_AUTH_CACHE="$(sam_auth_cache_path)"

# load_env DIR [FILE]: without FILE (or with FILE = DIR/.env) a
# missing file is skipped silently, as always. An explicit other
# FILE must exist -- an AKS run must never fall back to the lab .env
# or to built-in lab defaults.
load_env() {
  local project_dir="$1" env_file="${2:-}"
  if [ -n "$env_file" ] && [ "$env_file" != "$project_dir/.env" ] \
     && [ ! -f "$env_file" ]; then
    echo "ERROR: env file not found: $env_file" >&2
    return 1
  fi
  env_file="${env_file:-$project_dir/.env}"
  if [ -f "$env_file" ]; then
    set -a
    # shellcheck source=/dev/null
    . "$env_file"
    set +a
  fi
}

# Absolute physical path of an existing directory, or of a file in an
# existing directory; anything else comes back as given (without a
# trailing slash). Used only to compare paths.
_sam_abs_path() {
  local p="${1%/}" d
  if [ -d "$p" ]; then
    (CDPATH='' cd "$p" && pwd -P)
    return
  fi
  d="$(dirname "$p")"
  if [ -d "$d" ]; then
    printf '%s/%s\n' "$(CDPATH='' cd "$d" && pwd -P)" "$(basename "$p")"
  else
    printf '%s\n' "$p"
  fi
}

# sam_target_check PROJECT_DIR: SAM_ENV_FILE, SAM_URL and SAM_HOME
# must be all unset (the lab) or all set (a remote platform). A
# partial set would mix the two: the remote env file applied to the
# lab platform, or the lab login token sent to the remote URL. A
# remote run must also not use the lab CLI home (its login cache is
# the lab token) or the lab .env. Not run at source time: the demo
# scripts source this file and set SAM_URL for their own messages.
sam_target_check() {
  local project_dir="$1" v set_vars="" unset_vars=""
  for v in SAM_ENV_FILE SAM_URL SAM_HOME; do
    if [ -n "${!v:-}" ]; then
      set_vars="$set_vars $v"
    else
      unset_vars="$unset_vars $v"
    fi
  done
  [ -z "$set_vars" ] && return 0
  if [ -n "$unset_vars" ]; then
    echo "ERROR: partial target -${set_vars} set, but${unset_vars} not." >&2
    echo "  Set all three for a remote platform (aks_sam does) or none" >&2
    echo "  for the lab." >&2
    return 1
  fi
  case "$SAM_HOME" in
    /*) ;;
    *) echo "ERROR: SAM_HOME must be an absolute path." >&2; return 1 ;;
  esac
  if [ "$(_sam_abs_path "$SAM_HOME")" = "$(_sam_abs_path "$HOME")" ]; then
    echo "ERROR: SAM_HOME is the real HOME; the sam CLI would use the" >&2
    echo "  lab login cache." >&2
    return 1
  fi
  if [ "$(_sam_abs_path "$SAM_HOME")" = \
       "$(_sam_abs_path "$HOME/Library/Application Support/sam")" ]; then
    echo "ERROR: SAM_HOME is the lab sam home; a remote platform needs" >&2
    echo "  its own login cache." >&2
    return 1
  fi
  if [ "$(_sam_abs_path "$SAM_ENV_FILE")" = \
       "$(_sam_abs_path "$project_dir/.env")" ]; then
    echo "ERROR: SAM_ENV_FILE is the lab .env; a remote platform needs" >&2
    echo "  its own env file." >&2
    return 1
  fi
  # No token of the shell (or of the env file) reaches the remote
  # platform: the CLI honours SAM_AUTH_TOKEN before SAM_PLATFORM_TOKEN
  # and before its login cache. Only sam_auth_token sets it again, from
  # the remote login cache under SAM_HOME.
  unset SAM_AUTH_TOKEN SAM_PLATFORM_TOKEN
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
    echo ".env, or put 'sam' on the PATH. Some SAM delivery packages" >&2
    echo "ship it as solace-agent-mesh-<ver>-cli-<os>-<arch>.tar.gz;" >&2
    echo "otherwise install the matching CLI separately." >&2
    return 1
  fi
  echo "Using sam CLI: $SAM_CLI" >&2
}

# Platform URL for commands and messages (no trailing slash).
sam_base_url() {
  local url="${SAM_URL:-https://sam.solace.lab}"
  printf '%s\n' "${url%/}"
}

# Every sam CLI call of these scripts. With SAM_HOME set (remote
# platform) the CLI runs with HOME=$SAM_HOME, its own login cache,
# and without a shell SAM_PLATFORM_TOKEN (it would override that
# cache). Lab: the plain CLI, unchanged.
sam_cli_run() {
  if [ -n "${SAM_HOME:-}" ]; then
    env -u SAM_PLATFORM_TOKEN HOME="$SAM_HOME" "$SAM_CLI" "$@"
  else
    "$SAM_CLI" "$@"
  fi
}

# The login command for messages: the lab form unchanged; with
# SAM_HOME set the aks.sh wrapper, which runs the CLI with that HOME.
sam_login_cmd() {
  if [ -n "${SAM_HOME:-}" ]; then
    printf 'aks_sam sam auth login solace-lab --url %s\n' "$(sam_base_url)"
  else
    printf '%s auth login solace-lab --url %s\n' "${SAM_CLI:-sam}" \
      "$(sam_base_url)"
  fi
}

# The only way the agent-mesh-deployment scripts call `sam config`.
# With SAM_URL set, the platform is named explicitly (the manifests'
# target.url is the lab) and the CLI's own .env auto-load is off
# (the nearest .env up the tree is the LAB .env; ${VAR} references
# then resolve from the process environment only, which load_env
# filled from SAM_ENV_FILE).
sam_cli_config() {
  if [ -n "${SAM_URL:-}" ]; then
    sam_cli_run config "$@" --url "$SAM_URL" --no-dotenv
  else
    "$SAM_CLI" config "$@"
  fi
}

# `sam api` with the platform named explicitly when SAM_URL is set,
# so the token from sam_auth_token never goes to whatever single
# login another CLI home happens to cache.
sam_cli_api() {
  if [ -n "${SAM_URL:-}" ]; then
    sam_cli_run api --url "$SAM_URL" "$@"
  else
    "$SAM_CLI" api "$@"
  fi
}

sam_auth_token() {
  local cache
  cache="$(sam_auth_cache_path)"
  if [ ! -f "$cache" ]; then
    echo "ERROR: no sam CLI login cache. Log in first:" >&2
    echo "  $(sam_login_cmd)" >&2
    return 1
  fi
  if ! SAM_AUTH_TOKEN=$(python3 -c \
      "import json,sys;print(json.load(open(sys.argv[1]))['sam_access_token'])" \
      "$cache" 2>/dev/null); then
    echo "ERROR: could not read the sam login cache ($cache)." >&2
    echo "Re-login: $(sam_login_cmd)" >&2
    return 1
  fi
  export SAM_AUTH_TOKEN
}
