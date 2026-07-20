#!/bin/bash
set -euo pipefail

# =============================================================
# Load the offline SAM v2 images into the private registry
# =============================================================
# The SAM v2 app and str images are distributed as offline docker
# tarballs (arm64). This script loads them into the local Docker
# daemon, retags them for registry.solace.lab and pushes them.
#
# Requires: Rancher Desktop running, and a docker login session
# for registry.solace.lab (credentials from the registry setup in
# solace-lab-infrastructure).
#
# The bundled persistence images (postgres, seaweedfs) are public
# on Docker Hub and are NOT mirrored into the private registry.
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

REGISTRY="registry.solace.lab"
# Source refs as contained in the tarballs (docker load restores
# these names), and their target tags. Keep in sync with
# local-k8s-values.yaml (samDeployment.gwe.image / str.image).
APP_REF="solace-agent-mesh:2.225.14"
STR_REF="solace-agent-mesh-str:1.50.3"

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

# --- Load, tag, push one image ------------------------------------
load_and_push() {
  local ref="$1" tar="$2"
  local target="$REGISTRY/$ref"

  if docker image inspect "$ref" >/dev/null 2>&1; then
    echo "Image $ref already loaded - skipping docker load."
  else
    if [ -z "$tar" ] || [ ! -f "$tar" ]; then
      echo "ERROR: tarball for $ref not found."
      echo "Set SAM_APP_IMAGE_TAR / SAM_STR_IMAGE_TAR in .env to the"
      echo "offline image tarball paths."
      exit 1
    fi
    echo "Loading $ref from $tar ..."
    docker load -i "$tar"
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

load_and_push "$APP_REF" "$APP_TAR"
load_and_push "$STR_REF" "$STR_TAR"

echo "All SAM v2 images available in $REGISTRY:"
echo "  $REGISTRY/$APP_REF"
echo "  $REGISTRY/$STR_REF"
