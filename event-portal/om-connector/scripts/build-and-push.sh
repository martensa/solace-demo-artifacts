#!/bin/bash
# Build the custom OpenMetadata ingestion image with the Solace EP
# connector baked in, then push it to the lab's private registry.
#
# Tags:
#   - registry.solace.lab/openmetadata-ingestion-solace:<connector-version>
#   - registry.solace.lab/openmetadata-ingestion-solace:latest
#
# Override the OM version if needed:
#   OM_INGESTION_VERSION=1.11.14.0 ./scripts/build-and-push.sh
#
# Override the registry / image name if pushing somewhere else:
#   REGISTRY=ghcr.io/martensa IMAGE_NAME=om-eventportal-ingestion \
#     ./scripts/build-and-push.sh
#
# IMPORTANT: OM_INGESTION_VERSION must match ALDI's OM server version
# exactly (1.11.0.0 today). Bump only when ALDI upgrades their server.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Defaults (overridable via env) -----------------------------------------
OM_INGESTION_VERSION="${OM_INGESTION_VERSION:-1.11.0.0}"
REGISTRY="${REGISTRY:-registry.solace.lab}"
IMAGE_NAME="${IMAGE_NAME:-openmetadata-ingestion-solace}"
PUSH="${PUSH:-true}"

# --- Derive version from pyproject.toml ------------------------------------
# Portable across GNU sed and BSD sed (macOS): match `^version` and pull
# out the first double-quoted substring with `cut`.
CONNECTOR_VERSION=$(
  awk -F'"' '/^version[[:space:]]*=/{print $2; exit}' "$PROJECT_DIR/pyproject.toml"
)
if [ -z "$CONNECTOR_VERSION" ]; then
  echo "ERROR: could not read version from pyproject.toml" >&2
  exit 1
fi

FULL_TAG="${REGISTRY}/${IMAGE_NAME}:${CONNECTOR_VERSION}"
LATEST_TAG="${REGISTRY}/${IMAGE_NAME}:latest"

# --- CLI prerequisites -----------------------------------------------------
command -v docker >/dev/null 2>&1 || { echo "ERROR: docker not found."; exit 1; }

# --- Build -----------------------------------------------------------------
echo "Building ${FULL_TAG} (OM base ${OM_INGESTION_VERSION}) ..."
docker build \
  --build-arg "OM_INGESTION_VERSION=${OM_INGESTION_VERSION}" \
  -t "${FULL_TAG}" \
  -t "${LATEST_TAG}" \
  "${PROJECT_DIR}"

# --- Push ------------------------------------------------------------------
if [ "${PUSH}" = "true" ]; then
  echo "Pushing ${FULL_TAG} ..."
  docker push "${FULL_TAG}"
  docker push "${LATEST_TAG}"
  echo ""
  echo "----------------------------------------------------------------"
  echo "Image pushed:"
  echo "  ${FULL_TAG}"
  echo "  ${LATEST_TAG}"
  echo ""
  echo "Next step: flip the OM ingestion image in"
  echo "  openmetadata-deployment/local-k8s-deps-values.yaml"
  echo "to use this tag, then 'helm upgrade openmetadata-dependencies ...'."
  echo "----------------------------------------------------------------"
else
  echo "PUSH=false set -- skipping push. Image is in the local docker daemon."
fi
