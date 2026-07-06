#!/bin/bash
set -euo pipefail

# ============================================================
# Reliable lab workaround for the connector-package download.
#
# The Designer builds the connector package correctly server-side, but the
# vendor's WEB download serializes the whole package as base64-in-JSON
# synchronously; under QEMU emulation on Apple-silicon k3s that exceeds the
# UI's ~20s client timeout (HTTP 499), so the browser never saves the file.
# On native amd64 (OpenShift) the download works normally. This script pulls
# the freshly built package straight out of the pod instead.
#
# Usage:
#   ./extract-connector-package.sh [NAMESPACE] [OUTPUT_DIR]
#     NAMESPACE   default: db-designer
#     OUTPUT_DIR  default: $HOME/Downloads
#
# Trigger a package build first (click Download in the UI, or generate the
# entities) so the package exists on the volume, then run this.
# ============================================================

NS="${1:-db-designer}"
OUT="${2:-$HOME/Downloads}"

command -v kubectl >/dev/null 2>&1 || { echo "ERROR: kubectl not found."; exit 1; }
mkdir -p "$OUT"

POD=$(kubectl -n "$NS" get pod -l app.kubernetes.io/component=services \
  --no-headers 2>/dev/null | grep -v Terminating | awk '{print $1}' | head -1)
[ -n "$POD" ] || { echo "ERROR: services pod not found in namespace $NS."; exit 1; }

# Newest connector package dir = a folder that contains dependencies/entity.jar.
PKG=$(kubectl -n "$NS" exec "$POD" -c services -- sh -c '
  for d in $(ls -dt /app/tmp/entityFolders/*/*/ 2>/dev/null); do
    [ -f "${d}dependencies/entity.jar" ] && { printf "%s" "${d%/}"; break; }
  done')
[ -n "$PKG" ] || { echo "ERROR: no built connector package found. Trigger a build in the UI first."; exit 1; }

NAME=$(basename "$PKG")
echo "==> Packaging $NAME from pod $POD ..."
kubectl -n "$NS" exec "$POD" -c services -- sh -c \
  "cd \"$(dirname "$PKG")\" && rm -f \"/tmp/${NAME}.zip\" && jar cfM \"/tmp/${NAME}.zip\" \"$NAME\""

echo "==> Copying to $OUT/${NAME}.zip ..."
kubectl -n "$NS" cp "$POD:/tmp/${NAME}.zip" "$OUT/${NAME}.zip" -c services

echo ""
echo "Done: $OUT/${NAME}.zip"
kubectl -n "$NS" exec "$POD" -c services -- sh -c "unzip -l \"/tmp/${NAME}.zip\" 2>/dev/null | tail -n +4 | head -20" || true
