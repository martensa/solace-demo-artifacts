#!/bin/bash
set -euo pipefail

# =============================================================
# Load the offline SAM v2 images into the private registry
# =============================================================
# Every image the chart renders comes from the delivery package
# (arm64 docker tarballs): the gwe/awe app image, str, and the
# bundled persistence images postgres (postgresql StatefulSet +
# db-init) and seaweedfs (seaweedfs StatefulSet + s3-init). This
# script loads them into the local Docker daemon, retags them for
# registry.solace.lab and pushes them -- nothing is pulled from
# Docker Hub.
#
# The repository and tag to publish are read from
# local-k8s-values.yaml -- that file is the single source of
# truth, so a version bump is a one-line change there:
#   samDeployment.gwe.image                 <- SAM_APP_IMAGE_TAR
#   samDeployment.str.image                 <- SAM_STR_IMAGE_TAR
#   persistence-layer.postgresql.image      <- SAM_POSTGRES_IMAGE_TAR
#   persistence-layer.seaweedfs.image       <- SAM_SEAWEEDFS_IMAGE_TAR
# samDeployment.dbInit.image / s3Init.image must name the same
# repository:tag as their persistence-layer counterpart; the
# script refuses to run when they drift apart.
#
# The name a tarball restores is whatever the vendor baked in and
# does not have to match our pin, so the loaded reference is taken
# from the `docker load` output and retagged to the pinned one.
#
# Requires: Rancher Desktop running, and a docker login session
# for registry.solace.lab (credentials from the registry setup in
# solace-lab-infrastructure).
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

command -v docker >/dev/null 2>&1 || {
  echo "ERROR: docker not found in PATH."; exit 1
}
docker info >/dev/null 2>&1 || {
  echo "ERROR: docker daemon not reachable (is Rancher Desktop running?)."
  exit 1
}
[ -f "$VALUES" ] || { echo "ERROR: $VALUES not found."; exit 1; }

# --- Pinned references from local-k8s-values.yaml -----------------
# <dotted path to an image block> -> <repository>:<tag>
# Fails when the block does not point at $REGISTRY: an image that
# would come from anywhere else defeats the offline install.
pinned_ref() {
  python3 - "$VALUES" "$1" "$REGISTRY" <<'PY'
import sys, yaml
values, path, registry = sys.argv[1:4]
node = yaml.safe_load(open(values))
for key in path.split('.'):
    node = (node or {}).get(key)
if not isinstance(node, dict) or not node.get('repository') \
        or not node.get('tag'):
    sys.exit(f"ERROR: {path}: repository/tag not set in {values}")
if node.get('registry') != registry:
    sys.exit(f"ERROR: {path}.registry is {node.get('registry')!r},"
             f" expected {registry!r}")
print(f"{node['repository']}:{node['tag']}")
PY
}

APP_REF=$(pinned_ref samDeployment.gwe.image)
STR_REF=$(pinned_ref samDeployment.str.image)
PG_REF=$(pinned_ref persistence-layer.postgresql.image)
SW_REF=$(pinned_ref persistence-layer.seaweedfs.image)
DBINIT_REF=$(pinned_ref samDeployment.dbInit.image)
S3INIT_REF=$(pinned_ref samDeployment.s3Init.image)

if [ "$DBINIT_REF" != "$PG_REF" ]; then
  echo "ERROR: samDeployment.dbInit.image ($DBINIT_REF) differs from"
  echo "  persistence-layer.postgresql.image ($PG_REF). Pin both to"
  echo "  the postgres image of the delivery package."
  exit 1
fi
if [ "$S3INIT_REF" != "$SW_REF" ]; then
  echo "ERROR: samDeployment.s3Init.image ($S3INIT_REF) differs from"
  echo "  persistence-layer.seaweedfs.image ($SW_REF). Pin both to"
  echo "  the seaweedfs image of the delivery package."
  exit 1
fi

# --- Load, tag, push one image ------------------------------------
# <scope> as in purge-images.sh:
#   own     gwe/str -- the bare name (docker load, plus the pin) is
#           kept next to the registry tag; purge-images.sh manages
#           both.
#   mirror  postgres/seaweedfs -- Docker Hub names other workloads
#           use too, which purge-images.sh never touches. Only the
#           registry tag is created; the bare name docker load
#           restores is untagged again unless it existed before,
#           so a later purge really frees the old image.
load_and_push() { # <ref> <tarball> <name of the .env variable> <scope>
  local ref="$1" tar="$2" var="$3" scope="$4"
  local target="$REGISTRY/$ref"
  local load_out loaded short arch before=""

  # FORCE=1 re-loads from the tarball even if the tag is already
  # present locally (needed if a re-released tarball reuses a tag).
  if [ "${FORCE:-0}" != "1" ] && docker image inspect "$target" >/dev/null 2>&1
  then
    echo "Image $target already present - skipping docker load"
    echo "  (FORCE=1 to reload from the tarball)."
    # Push the registry tag as it is. Re-tagging from the bare
    # name here could pick up a same-named image pulled from
    # Docker Hub since (e.g. postgres:18.0-trixie).
  else
    if [ -z "$tar" ] || [ ! -f "$tar" ]; then
      echo "ERROR: tarball for $ref not found."
      echo "Set $var in .env to the offline image tarball path"
      echo "(quoted if it contains a space)."
      exit 1
    fi
    if [ "$scope" = "mirror" ]; then
      # Bare names present BEFORE the load (short form, as compared
      # below) -- one of them may be a Docker Hub pull in use.
      before=$(docker images --format '{{.Repository}}:{{.Tag}}' \
        | sed 's#^docker\.io/##; s#^library/##')
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
    # The package tarballs carry fully qualified Docker Hub names
    # (docker.io/library/postgres:..., docker.io/chrislusf/...);
    # compare in the short form docker itself prints.
    short="${loaded#docker.io/}"
    short="${short#library/}"
    if [ "$short" != "$ref" ]; then
      echo "NOTE: the tarball restored '$loaded', which differs from the"
      echo "  pin '$ref' in local-k8s-values.yaml. Retagging to the pin."
      echo "  If the version part differs, fix the pin instead."
    fi
    echo "Tagging $loaded -> $target"
    if [ "$scope" = "mirror" ]; then
      docker tag "$loaded" "$target"
      # Drop the bare tag the load created (a TAG only: never by
      # image ID, never -f -- the image stays under $target).
      case "$loaded" in
        sha256:*) ;;            # untagged tarball: no bare name created
        "$REGISTRY"/*) ;;       # not a bare name
        *)
          case $'\n'"$before"$'\n' in
            *$'\n'"$short"$'\n'*)
              echo "  Keeping the bare tag $short: it existed before this load." ;;
            *)
              if docker rmi "$loaded" >/dev/null; then
                echo "  Untagged the bare $short (only $target remains)."
              else
                echo "WARNING: could not untag the bare $loaded."
              fi ;;
          esac ;;
      esac
    else
      docker tag "$loaded" "$ref"
      docker tag "$loaded" "$target"
    fi
  fi

  arch=$(docker image inspect --format '{{.Architecture}}' "$target")
  if [ "$arch" != "arm64" ]; then
    echo "WARNING: $target is $arch; the Rancher Desktop node is arm64."
  fi

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
echo "  gwe/awe:              $APP_REF"
echo "  str:                  $STR_REF"
echo "  postgresql + db-init: $PG_REF"
echo "  seaweedfs + s3-init:  $SW_REF"
echo ""

load_and_push "$APP_REF" "${SAM_APP_IMAGE_TAR:-}"       SAM_APP_IMAGE_TAR       own
load_and_push "$STR_REF" "${SAM_STR_IMAGE_TAR:-}"       SAM_STR_IMAGE_TAR       own
load_and_push "$PG_REF"  "${SAM_POSTGRES_IMAGE_TAR:-}"  SAM_POSTGRES_IMAGE_TAR  mirror
load_and_push "$SW_REF"  "${SAM_SEAWEEDFS_IMAGE_TAR:-}" SAM_SEAWEEDFS_IMAGE_TAR mirror

echo "All SAM v2 images available in $REGISTRY:"
echo "  $REGISTRY/$APP_REF"
echo "  $REGISTRY/$STR_REF"
echo "  $REGISTRY/$PG_REF"
echo "  $REGISTRY/$SW_REF"
