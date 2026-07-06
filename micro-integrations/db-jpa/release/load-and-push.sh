#!/bin/bash
set -euo pipefail

# ============================================================
# db-designer distribution bundle -- customer-side image loader
#
# Loads the bundled images into the local docker daemon, retags them
# for YOUR registry, pushes them, and prints the Helm values to use.
#
# Usage (from the unpacked bundle directory):
#   ./scripts/load-and-push.sh <registry-prefix>
#   e.g. ./scripts/load-and-push.sh registry.example.com/solace
#
# Requirements: docker CLI logged in to the target registry.
# ============================================================

REGISTRY="${1:-}"
[ -n "$REGISTRY" ] || { echo "Usage: $0 <registry-prefix>"; exit 1; }
REGISTRY="${REGISTRY%/}"

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(cat "$BUNDLE_DIR/VERSION")"

command -v docker >/dev/null 2>&1 || { echo "ERROR: docker not found."; exit 1; }

IMAGES="connector-designer-services connector-designer-ui db-designer-artifacts-seed"

echo "==> Loading images from $BUNDLE_DIR/images ..."
for name in $IMAGES; do
  docker load -i "$BUNDLE_DIR/images/$name-$VERSION.tar"
done

echo "==> Tagging and pushing to $REGISTRY ..."
for name in $IMAGES; do
  docker tag "$name:$VERSION" "$REGISTRY/$name:$VERSION"
  docker push "$REGISTRY/$name:$VERSION"
done

cat <<EOF

Done. Set these values for the Helm install (values-openshift.yaml or
your own values file):

image:
  services:
    repository: $REGISTRY/connector-designer-services
    tag: "$VERSION"
  ui:
    repository: $REGISTRY/connector-designer-ui
    tag: "$VERSION"
servicesApp:
  artifacts:
    seedImage: $REGISTRY/db-designer-artifacts-seed:$VERSION

Then:
  helm install db-designer charts/db-designer-$VERSION.tgz \\
    -f <your-values>.yaml --namespace db-designer --create-namespace
EOF
