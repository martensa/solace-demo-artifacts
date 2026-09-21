#!/bin/bash
set -euo pipefail

# =============================================================
# purge-images.sh -- remove SAM images that the current
# local-k8s-values.yaml does NOT pin.
# =============================================================
# After a version upgrade the old gwe/str images stay behind in
# two places, both outside the deleted namespace:
#
#   1. the local Docker daemon (docker load from the offline
#      tarballs, plus the registry.solace.lab retag) -- several
#      GB per version
#   2. the private registry registry.solace.lab
#
# This script treats local-k8s-values.yaml as the single source
# of truth: the tags pinned there are KEPT, every other tag of
# the SAM repositories is purged. Nothing is hardcoded, so it
# stays correct across upgrades.
#
# Registry deletion needs the registry to run with
# REGISTRY_STORAGE_DELETE_ENABLED=true. If it does not, the
# manifest DELETE returns 405 and the script says so instead of
# failing -- the local daemon is cleaned either way.
#
# Usage:
#   ./purge-images.sh [--dry-run] [--yes] [--local-only]
#                     [--registry-only]
#
#   --dry-run        list what would be removed, remove nothing
#   --yes            skip the confirmation prompt
#   --local-only     only the local Docker daemon
#   --registry-only  only registry.solace.lab
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

REGISTRY="registry.solace.lab"
VALUES="$PROJECT_DIR/local-k8s-values.yaml"

DRY_RUN=0
ASSUME_YES=0
DO_LOCAL=1
DO_REGISTRY=1

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)       DRY_RUN=1 ;;
    --yes|-y)        ASSUME_YES=1 ;;
    --local-only)    DO_REGISTRY=0 ;;
    --registry-only) DO_LOCAL=0 ;;
    -h|--help)       awk '/^# Usage:/{f=1} f && /^# ==/{exit} f' "$0" \
                       | sed 's/^# \{0,1\}//'
                     exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
  shift
done

[ -f "$VALUES" ] || { echo "ERROR: $VALUES not found." >&2; exit 1; }

# --- Tags pinned by the current values file ------------------------
# Emits "<repository> <tag>" for gwe and str.
# (a read loop rather than mapfile: /bin/bash on macOS is 3.2)
PINNED=()
while IFS= read -r line; do
  [ -n "$line" ] && PINNED+=("$line")
done < <(python3 -c "
import yaml
v = yaml.safe_load(open('$VALUES'))
for comp in ('gwe', 'str'):
    i = v['samDeployment'][comp]['image']
    print(i['repository'], i['tag'])
")

if [ "${#PINNED[@]}" -eq 0 ]; then
  echo "ERROR: could not read the pinned image tags from $VALUES." >&2
  exit 1
fi

echo "Pinned by local-k8s-values.yaml (kept):"
for p in "${PINNED[@]}"; do
  echo "  ${p% *}:${p#* }"
done
echo ""

repo_is_pinned() { # <repository> <tag>
  local r t
  for p in "${PINNED[@]}"; do
    r="${p% *}"; t="${p#* }"
    [ "$1" = "$r" ] && [ "$2" = "$t" ] && return 0
  done
  return 1
}

SAM_REPOS=()
for p in "${PINNED[@]}"; do SAM_REPOS+=("${p% *}"); done

# --- Collect the local Docker images to purge ----------------------
LOCAL_PURGE=()
if [ "$DO_LOCAL" -eq 1 ]; then
  if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    echo "WARNING: docker daemon not reachable -- skipping local cleanup."
    DO_LOCAL=0
  else
    while read -r ref; do
      [ -n "$ref" ] || continue
      # ref is either <repo>:<tag> or <registry>/<repo>:<tag>
      local_tag="${ref##*:}"
      local_repo="${ref%:*}"
      local_repo="${local_repo#"$REGISTRY"/}"
      case " ${SAM_REPOS[*]} " in
        *" $local_repo "*) ;;
        *) continue ;;
      esac
      repo_is_pinned "$local_repo" "$local_tag" || LOCAL_PURGE+=("$ref")
    done < <(docker images --format '{{.Repository}}:{{.Tag}}' \
               | grep -E '(^|/)solace-agent-mesh(-str)?:' || true)
  fi
fi

# --- Collect the registry tags to purge ----------------------------
# Credentials come from the existing `docker login` session: either
# inline in ~/.docker/config.json ("auth") or, as Rancher Desktop on
# macOS sets it up, in a credential helper (credHelpers entry or the
# global credsStore, e.g. osxkeychain) queried through its
# docker-credential-<helper> binary.
REG_AUTH=""
registry_ready() {
  [ -f "$HOME/.docker/config.json" ] || return 1
  REG_AUTH=$(python3 -c "
import base64, json, subprocess, sys
cfg = json.load(open('$HOME/.docker/config.json'))
keys = ('$REGISTRY', 'https://$REGISTRY', 'https://$REGISTRY/v2/')
for key in keys:
    entry = cfg.get('auths', {}).get(key) or {}
    if entry.get('auth'):
        sys.stdout.write(base64.b64decode(entry['auth']).decode())
        raise SystemExit
helper = next((cfg.get('credHelpers', {}).get(k) for k in keys
               if cfg.get('credHelpers', {}).get(k)), cfg.get('credsStore'))
if helper:
    for key in keys:
        r = subprocess.run(['docker-credential-' + helper, 'get'],
                           input=key, capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            c = json.loads(r.stdout)
            sys.stdout.write(c['Username'] + ':' + c['Secret'])
            break
" 2>/dev/null) || return 1
  [ -n "$REG_AUTH" ] || return 1
}

reg_curl() { curl -sS -u "$REG_AUTH" "$@"; }

REG_PURGE=()
if [ "$DO_REGISTRY" -eq 1 ]; then
  if ! registry_ready; then
    echo "WARNING: no stored credentials for $REGISTRY in"
    echo "  ~/.docker/config.json -- run 'docker login $REGISTRY' to"
    echo "  include the registry in the purge. Skipping it for now."
    DO_REGISTRY=0
  else
    for repo in "${SAM_REPOS[@]}"; do
      tags=$(reg_curl "https://$REGISTRY/v2/$repo/tags/list" 2>/dev/null \
               | python3 -c "
import json, sys
try:
    print('\n'.join(json.load(sys.stdin).get('tags') or []))
except Exception:
    pass
" || true)
      while read -r tag; do
        [ -n "$tag" ] || continue
        repo_is_pinned "$repo" "$tag" || REG_PURGE+=("$repo:$tag")
      done <<< "$tags"
    done
  fi
fi

# --- Report --------------------------------------------------------
if [ "${#LOCAL_PURGE[@]}" -eq 0 ] && [ "${#REG_PURGE[@]}" -eq 0 ]; then
  echo "Nothing to purge: no unpinned SAM images found."
  exit 0
fi

if [ "${#LOCAL_PURGE[@]}" -gt 0 ]; then
  echo "Local Docker images to remove:"
  printf '  %s\n' "${LOCAL_PURGE[@]}"
  echo ""
fi
if [ "${#REG_PURGE[@]}" -gt 0 ]; then
  echo "Registry manifests to delete ($REGISTRY):"
  printf '  %s\n' "${REG_PURGE[@]}"
  echo ""
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "--dry-run: nothing removed."
  exit 0
fi

if [ "$ASSUME_YES" -ne 1 ]; then
  read -r -p "Remove these images? [y/N] " answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) echo "Aborted."; exit 0 ;;
  esac
fi

# --- Purge the registry first --------------------------------------
# (a local image is cheap to reload from the tarball, a registry
# manifest is not -- fail loudly there while the local copy is
# still around.)
DELETE_DISABLED=0
for ref in "${REG_PURGE[@]+"${REG_PURGE[@]}"}"; do
  repo="${ref%:*}"; tag="${ref##*:}"
  digest=$(reg_curl -o /dev/null -D - \
    -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
    -H 'Accept: application/vnd.oci.image.manifest.v1+json' \
    -H 'Accept: application/vnd.docker.distribution.manifest.list.v2+json' \
    -H 'Accept: application/vnd.oci.image.index.v1+json' \
    "https://$REGISTRY/v2/$repo/manifests/$tag" 2>/dev/null \
    | tr -d '\r' | awk -F': ' 'tolower($1)=="docker-content-digest"{print $2}')

  if [ -z "$digest" ]; then
    echo "WARNING: no digest for $ref -- skipped."
    continue
  fi

  code=$(reg_curl -o /dev/null -w '%{http_code}' -X DELETE \
    "https://$REGISTRY/v2/$repo/manifests/$digest" 2>/dev/null || echo "000")
  case "$code" in
    202|200|404) echo "Deleted from registry: $ref" ;;
    405|501)     echo "Registry refuses deletes (HTTP $code) for $ref"
                 DELETE_DISABLED=1 ;;
    *)           echo "WARNING: delete of $ref returned HTTP $code" ;;
  esac
done

if [ "$DELETE_DISABLED" -eq 1 ]; then
  cat <<'EOF'

The registry runs without REGISTRY_STORAGE_DELETE_ENABLED=true, so
old manifests cannot be removed through the API. They occupy
registry storage but are never pulled again (nothing references
them). To clear them, enable deletion on the registry Deployment in
solace-lab-infrastructure and re-run this script, or recreate the
registry volume.
EOF
fi

# --- Purge the local daemon ----------------------------------------
for ref in "${LOCAL_PURGE[@]+"${LOCAL_PURGE[@]}"}"; do
  if docker rmi "$ref" >/dev/null 2>&1; then
    echo "Removed local image: $ref"
  else
    echo "WARNING: could not remove $ref (in use by a container?)"
  fi
done

if [ "$DO_LOCAL" -eq 1 ]; then
  echo ""
  echo "Reclaiming dangling layers ..."
  docker image prune -f >/dev/null 2>&1 || true
fi

echo ""
echo "Image purge complete."
