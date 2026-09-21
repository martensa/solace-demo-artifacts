#!/bin/bash
set -euo pipefail

# =============================================================
# Load the offline SAM v2 images into the private registry
# =============================================================
# The SAM v2 app and str images are distributed as offline docker
# tarballs (arm64). This script loads them into the local Docker
# daemon, retags them for registry.solace.lab and pushes them.
#
# The repository and tag to publish are read from
# local-k8s-values.yaml (samDeployment.gwe.image /
# samDeployment.str.image) -- that file is the single source of
# truth, so a version bump is a one-line change there.
#
# The name a tarball restores is whatever the vendor baked in and
# does not have to match our pin, so the loaded reference is taken
# from the `docker load` output and retagged to the pinned one.
#
# Requires: Rancher Desktop running, and a docker login session
# for registry.solace.lab (credentials from the registry setup in
# solace-lab-infrastructure).
#
# The bundled persistence images (postgres, seaweedfs) are public
# on Docker Hub and are NOT mirrored into the private registry.
#
# Usage:
#   ./load-images.sh          # skip images already in the daemon
#   FORCE=1 ./load-images.sh  # re-load from the tarballs
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

REGISTRY="registry.solace.lab"
VALUES="$PROJECT_DIR/local-k8s-values.yaml"

# --- Load environment variables -----------------------------------
if [ -f "$PROJECT_DIR/.env" ]; then
  # shellcheck source=/dev/null
  . "$PROJECT_DIR/.env"
fi

APP_TAR="${SAM_APP_IMAGE_TAR:-}"
STR_TAR="${SAM_STR_IMAGE_TAR:-}"

command -v docker >/dev/null 2>&1 || {
  echo "ERROR: docker not found in PATH."; exit 1
}
docker info >/dev/null 2>&1 || {
  echo "ERROR: docker daemon not reachable (is Rancher Desktop running?)."
  exit 1
}
[ -f "$VALUES" ] || { echo "ERROR: $VALUES not found."; exit 1; }

# --- Pinned references from local-k8s-values.yaml -----------------
pinned_ref() { # <component> -> <repository>:<tag>
  python3 -c "
import yaml
v = yaml.safe_load(open('$VALUES'))
i = v['samDeployment']['$1']['image']
print('{}:{}'.format(i['repository'], i['tag']))
"
}

APP_REF=$(pinned_ref gwe)
STR_REF=$(pinned_ref str)

if [ -z "$APP_REF" ] || [ -z "$STR_REF" ]; then
  echo "ERROR: could not read the pinned image references from $VALUES."
  exit 1
fi

# --- Load, tag, push one image ------------------------------------
load_and_push() {
  local ref="$1" tar="$2"
  local target="$REGISTRY/$ref"
  local load_out loaded

  # FORCE=1 re-loads from the tarball even if the tag is already
  # present locally (needed if a re-released tarball reuses a tag).
  if [ "${FORCE:-0}" != "1" ] && docker image inspect "$target" >/dev/null 2>&1
  then
    echo "Image $target already present - skipping docker load"
    echo "  (FORCE=1 to reload from the tarball)."
  else
    if [ -z "$tar" ] || [ ! -f "$tar" ]; then
      echo "ERROR: tarball for $ref not found."
      echo "Set SAM_APP_IMAGE_TAR / SAM_STR_IMAGE_TAR in .env to the"
      echo "offline image tarball paths."
      exit 1
    fi
    echo "Loading $ref from $tar ..."
    load_out=$(docker load -i "$tar")
    echo "$load_out"

    # "Loaded image: repo:tag" or, for an untagged tarball,
    # "Loaded image ID: sha256:...".
    loaded=$(printf '%s\n' "$load_out" \
      | sed -n 's/^Loaded image: *//p' | tail -1)
    if [ -z "$loaded" ]; then
      loaded=$(printf '%s\n' "$load_out" \
        | sed -n 's/^Loaded image ID: *//p' | tail -1)
    fi
    if [ -z "$loaded" ]; then
      echo "ERROR: could not tell what 'docker load' restored from $tar."
      exit 1
    fi
    if [ "$loaded" != "$ref" ]; then
      echo "NOTE: the tarball restored '$loaded', which differs from the"
      echo "  pin '$ref' in local-k8s-values.yaml. Retagging to the pin."
      echo "  If the version part differs, fix the pin instead."
    fi
    echo "Tagging $loaded -> $ref"
    docker tag "$loaded" "$ref"
  fi

  echo "Tagging $ref -> $target"
  docker tag "$ref" "$target"

  echo "Pushing $target ..."
  if ! docker push "$target"; then
    echo ""
    echo "ERROR: push to $REGISTRY failed. If this is an auth error,"
    echo "log in first:  docker login $REGISTRY"
    echo "(credentials from the registry setup in"
    echo " solace-lab-infrastructure/registry)"
    exit 1
  fi
  echo ""
}

echo "Pinned by local-k8s-values.yaml:"
echo "  gwe/awe: $APP_REF"
echo "  str:     $STR_REF"
echo ""

load_and_push "$APP_REF" "$APP_TAR"
load_and_push "$STR_REF" "$STR_TAR"

echo "All SAM v2 images available in $REGISTRY:"
echo "  $REGISTRY/$APP_REF"
echo "  $REGISTRY/$STR_REF"
