#!/bin/bash
set -euo pipefail

# ============================================================
# db-jpa DB Designer -- distribution bundle packager
#
# Produces a self-contained, versioned customer bundle:
#   dist/db-designer-dist-<version>.zip
#     MANIFEST.txt          version, git SHA, date, image IDs, sha256 sums
#     VERSION
#     charts/db-designer-<version>.tgz
#     images/*.tar          hardened services/ui + artifacts seed (amd64)
#     connector/            connector jar + jpa_start.sh + examples/ + empty
#                           Config/ and dependencies/ placeholders
#     scripts/load-and-push.sh
#     docs/*.md
#
# The seed image builds the DB CLI FROM SOURCE (multi-stage), so a bundle
# always contains the current CLI -- freshness by construction.
#
# Usage: ./package-release.sh <version> [--no-archive]
#   <version>     bundle version, e.g. 1.0.0 (becomes image tag + chart ver)
#   --no-archive  leave the dist directory unzipped (faster for testing)
# ============================================================

VERSION="${1:-}"
[ -n "$VERSION" ] || { echo "Usage: $0 <version> [--no-archive]"; exit 1; }
NO_ARCHIVE="${2:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MI_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"           # micro-integrations/db-jpa
DESIGNER_DIR="$MI_DIR/DB Designer"
CONNECTOR_DIR="$MI_DIR/DB Connector"
DIST_ROOT="$MI_DIR/dist"
STAGE="$DIST_ROOT/db-designer-dist-$VERSION"
PLATFORM="${PLATFORM:-linux/amd64}"
APP_VERSION="2.0.2"

for c in docker helm git zip shasum; do
  command -v "$c" >/dev/null 2>&1 || { echo "ERROR: $c not found."; exit 1; }
done

# --- Preflight: vendor base images ---------------------------------
ensure_base() {
  local name="$1" tar="$2"
  docker image inspect "$name:latest" >/dev/null 2>&1 && return 0
  [ -f "$tar" ] || { echo "ERROR: base image $name missing and tar not found: $tar"; exit 1; }
  echo "==> docker load $(basename "$tar") ..."
  docker load -i "$tar" >/dev/null
}
ensure_base connector_designer_services "$DESIGNER_DIR/connector_designer_services.tar"
ensure_base connector_designer_ui       "$DESIGNER_DIR/connector_designer_ui.tar"

GIT_SHA="$(git -C "$MI_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "==> Packaging db-designer-dist-$VERSION (git $GIT_SHA, $PLATFORM)"
rm -rf "$STAGE"
mkdir -p "$STAGE/charts" "$STAGE/images" "$STAGE/connector" \
         "$STAGE/scripts" "$STAGE/docs"

# --- 1. Build images (amd64 for the customer cluster) --------------
echo "==> [1/5] Building images ..."
docker build --platform "$PLATFORM" \
  -t "db-designer-artifacts-seed:$VERSION" \
  -f "$DESIGNER_DIR/hardened-images/Dockerfile.artifacts-seed" "$MI_DIR"
docker build --platform "$PLATFORM" \
  --build-arg BASE=connector_designer_services:latest \
  -t "connector-designer-services:$VERSION" \
  -f "$DESIGNER_DIR/hardened-images/Dockerfile.services" \
  "$DESIGNER_DIR/hardened-images"
docker build --platform "$PLATFORM" \
  --build-arg BASE=connector_designer_ui:latest \
  -t "connector-designer-ui:$VERSION" \
  -f "$DESIGNER_DIR/hardened-images/Dockerfile.ui" \
  "$DESIGNER_DIR/hardened-images"

# --- 2. Helm chart ---------------------------------------------------
echo "==> [2/5] Packaging Helm chart ..."
helm lint "$DESIGNER_DIR/charts/db-designer" >/dev/null
helm package "$DESIGNER_DIR/charts/db-designer" \
  --version "$VERSION" --app-version "$APP_VERSION" \
  --destination "$STAGE/charts" >/dev/null

# --- 3. Export images ------------------------------------------------
echo "==> [3/5] Exporting images (docker save) ..."
docker save "connector-designer-services:$VERSION" \
  -o "$STAGE/images/connector-designer-services-$VERSION.tar"
docker save "connector-designer-ui:$VERSION" \
  -o "$STAGE/images/connector-designer-ui-$VERSION.tar"
docker save "db-designer-artifacts-seed:$VERSION" \
  -o "$STAGE/images/db-designer-artifacts-seed-$VERSION.tar"

# --- 4. Connector binaries, scripts, docs ----------------------------
echo "==> [4/5] Collecting connector binaries, scripts and docs ..."
cp "$CONNECTOR_DIR"/pubsubplus-connector-database-*.jar "$STAGE/connector/" 2>/dev/null \
  || echo "WARNING: no connector jar found in DB Connector/ -- bundle ships without it."
# One generic launcher works for source and sink (each is a self-contained
# package whose own Config/ decides the direction). Config/ + dependencies/
# are placeholders the customer fills from a DB Designer package; examples/
# carries reference source and sink configs.
cp "$CONNECTOR_DIR"/jpa_start.sh "$STAGE/connector/"
cp -R "$CONNECTOR_DIR/examples" "$STAGE/connector/examples"
mkdir -p "$STAGE/connector/Config" "$STAGE/connector/dependencies"
cp "$SCRIPT_DIR/load-and-push.sh" "$STAGE/scripts/load-and-push.sh"
chmod +x "$STAGE/scripts/load-and-push.sh"
cp "$DESIGNER_DIR/docs/"*.md "$STAGE/docs/"
echo "$VERSION" > "$STAGE/VERSION"

# --- 5. Manifest + archive -------------------------------------------
echo "==> [5/5] Writing MANIFEST and archiving ..."
{
  echo "db-designer distribution bundle"
  echo "version:    $VERSION"
  echo "appVersion: $APP_VERSION"
  echo "gitSha:     $GIT_SHA"
  echo "built:      $BUILD_DATE"
  echo "platform:   $PLATFORM"
  echo ""
  echo "image IDs:"
  for img in "connector-designer-services:$VERSION" \
             "connector-designer-ui:$VERSION" \
             "db-designer-artifacts-seed:$VERSION"; do
    echo "  $img  $(docker image inspect --format '{{.Id}}' "$img")"
  done
  echo ""
  echo "sha256:"
  (cd "$STAGE" && find . -type f ! -name MANIFEST.txt -exec shasum -a 256 {} \; | sort -k2)
} > "$STAGE/MANIFEST.txt"

if [ "$NO_ARCHIVE" = "--no-archive" ]; then
  echo "Done (unarchived): $STAGE"
else
  (cd "$DIST_ROOT" && rm -f "db-designer-dist-$VERSION.zip" \
    && zip -1 -r -q "db-designer-dist-$VERSION.zip" "db-designer-dist-$VERSION")
  du -h "$DIST_ROOT/db-designer-dist-$VERSION.zip" | awk '{print "Done: "$2" ("$1")"}'
fi
