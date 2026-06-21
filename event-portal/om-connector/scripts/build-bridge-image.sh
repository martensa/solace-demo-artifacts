#!/bin/bash
# Build the standalone Solace EP -> OpenMetadata bridge image (Wave 5 / #15)
# from Dockerfile.bridge, then push it to the lab's private registry.
#
# The tag is derived from pyproject.toml so the Helm chart's appVersion /
# image.tag stay in lockstep with the connector version (mirrors
# build-and-push.sh for the ingestion image).
#
# Tags:
#   - registry.solace.lab/om-eventportal-bridge:<connector-version>
#   - registry.solace.lab/om-eventportal-bridge:latest
#
# Override registry / name / skip push:
#   REGISTRY=ghcr.io/martensa IMAGE_NAME=om-eventportal-bridge \
#     PUSH=false ./scripts/build-bridge-image.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

REGISTRY="${REGISTRY:-registry.solace.lab}"
IMAGE_NAME="${IMAGE_NAME:-om-eventportal-bridge}"
PUSH="${PUSH:-true}"

# --- Derive version from pyproject.toml (matches build-and-push.sh) ---------
CONNECTOR_VERSION=$(
  awk -F'"' '/^version[[:space:]]*=/{print $2; exit}' "$PROJECT_DIR/pyproject.toml"
)
if [ -z "$CONNECTOR_VERSION" ]; then
  echo "ERROR: could not read version from pyproject.toml" >&2
  exit 1
fi

FULL_TAG="${REGISTRY}/${IMAGE_NAME}:${CONNECTOR_VERSION}"
LATEST_TAG="${REGISTRY}/${IMAGE_NAME}:latest"

command -v docker >/dev/null 2>&1 || { echo "ERROR: docker not found."; exit 1; }

echo "Building ${FULL_TAG} (bridge image) ..."
docker build \
  -f "${PROJECT_DIR}/Dockerfile.bridge" \
  -t "${FULL_TAG}" \
  -t "${LATEST_TAG}" \
  "${PROJECT_DIR}"

if [ "$PUSH" = "true" ]; then
  echo "Pushing ${FULL_TAG} and ${LATEST_TAG} ..."
  docker push "${FULL_TAG}"
  docker push "${LATEST_TAG}"
else
  echo "PUSH=false -> skipping push. Built ${FULL_TAG}."
fi

echo "Done. Chart appVersion should match: ${CONNECTOR_VERSION}"
