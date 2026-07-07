#!/bin/bash
set -euo pipefail

# Build the hardened DB Designer overlay images (non-root, OpenShift
# arbitrary-UID compatible) and optionally push them to a registry.
#
# Usage:
#   ./build.sh [REGISTRY] [TAG]
#     REGISTRY  target registry, e.g. registry.solace.lab or the customer's
#               OpenShift registry. Omit to build locally without pushing.
#     TAG       image tag (default: 2.0.2-hardened)
#
# Env overrides:
#   PLATFORM       target platform (default linux/amd64 -- the vendor images
#                  are amd64-only; build on an amd64 host or CI runner).
#   SERVICES_BASE  base image for services (default connector_designer_services:latest)
#   UI_BASE        base image for ui       (default connector_designer_ui:latest)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY="${1:-}"
TAG="${2:-2.0.2-hardened}"
PLATFORM="${PLATFORM:-linux/amd64}"

command -v docker >/dev/null 2>&1 || { echo "ERROR: docker not found."; exit 1; }

build_one() {
  local name="$1" dockerfile="$2" base="$3"
  local ref="${name}:${TAG}"
  [ -n "$REGISTRY" ] && ref="${REGISTRY}/${ref}"
  echo "==> building $ref (base: $base, platform: $PLATFORM)"
  docker build --platform "$PLATFORM" \
    --build-arg BASE="$base" \
    -t "$ref" \
    -f "$SCRIPT_DIR/$dockerfile" "$SCRIPT_DIR"
  if [ -n "$REGISTRY" ]; then
    echo "==> pushing $ref"
    docker push "$ref"
  fi
  echo "$ref"
}

build_one connector_designer_services Dockerfile.services \
  "${SERVICES_BASE:-connector_designer_services:latest}"
build_one connector_designer_ui Dockerfile.ui \
  "${UI_BASE:-connector_designer_ui:latest}"

echo ""
echo "Done. In values-openshift.yaml point image.services.repository /"
echo "image.ui.repository at these refs (tag ${TAG}); with hardened images"
echo "you can set openshift.scc.create=false and podSecurityContext"
echo "runAsNonRoot=true."
