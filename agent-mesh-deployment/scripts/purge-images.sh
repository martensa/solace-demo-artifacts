#!/bin/bash
set -euo pipefail

# =============================================================
# purge-images.sh -- remove SAM images that the current
# local-k8s-values.yaml does NOT pin.
# =============================================================
# After a version upgrade the old gwe/str (and, when the delivery
# moves them, postgres/seaweedfs) images stay behind in two
# places, both outside the deleted namespace:
#
#   1. the local Docker daemon (docker load from the offline
#      tarballs, plus the registry.solace.lab retag) -- several
#      GB per version
#   2. the private registry registry.solace.lab
#
# This script treats local-k8s-values.yaml as the single source
# of truth: the tags pinned there are KEPT, every other tag of
# the SAM repositories is purged. Nothing is hardcoded, so it
# stays correct across upgrades. For postgres and
# chrislusf/seaweedfs only the registry.solace.lab refs count as
# SAM's: the bare Docker Hub names (local postgres:*, used by
# other workloads too) are never touched -- see PINNED below.
# A registry tag that shares its manifest with a pinned tag is
# kept as well (deleting the manifest would drop the pin too).
# This fails closed: when a pinned tag's digest cannot be
# resolved, its whole repository is skipped. A repository whose
# tag list cannot be read -- or a registry with no stored login --
# is reported as NOT checked; any of these makes the run exit 1
# after purging what it could check.
#
# Registry deletion needs the registry to run with
# REGISTRY_STORAGE_DELETE_ENABLED=true. If it does not, the
# manifest DELETE returns 405 and the script says so instead of
# failing -- the local daemon is cleaned either way. A DELETE
# frees no registry disk by itself: after one, the script prints
# the registry's garbage-collect command.
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
# Emits "<repository> <tag> <scope>" for every image block the
# deployment pulls from $REGISTRY (deduplicated: db-init/s3-init
# share their repository:tag with postgresql/seaweedfs).
#   scope "own":    gwe, str -- repositories only SAM uses, so the
#                   bare local name (docker load) is managed too.
#   scope "mirror": postgres, chrislusf/seaweedfs -- Docker Hub
#                   names that other workloads use as well (the
#                   demo postgres container, db-designer, iam).
#                   Only the $REGISTRY/<repo> refs are managed;
#                   bare local postgres:* / chrislusf/seaweedfs:*
#                   images are NEVER touched.
# A block on $REGISTRY without a usable repository/tag aborts the
# run (as load-images.sh's pinned_ref does) -- a partial pin list
# would mark the missing pin's tags as unpinned.
read_pins() {
  python3 - "$VALUES" "$REGISTRY" <<'PY'
import sys, yaml
values, registry = sys.argv[1:3]
v = yaml.safe_load(open(values))
blocks = (
    ('samDeployment.gwe.image', 'own'),
    ('samDeployment.str.image', 'own'),
    ('persistence-layer.postgresql.image', 'mirror'),
    ('samDeployment.dbInit.image', 'mirror'),
    ('persistence-layer.seaweedfs.image', 'mirror'),
    ('samDeployment.s3Init.image', 'mirror'),
)
seen = set()
for path, scope in blocks:
    node = v
    for key in path.split('.'):
        node = (node or {}).get(key)
    if not isinstance(node, dict) or node.get('registry') != registry:
        continue  # not served from our registry -> not ours to purge
    repo, tag = node.get('repository'), node.get('tag')
    if not repo or not tag:
        sys.exit(f"ERROR: {path}: repository/tag not set in {values}")
    if any(c.isspace() for c in f"{repo}{tag}"):
        sys.exit(f"ERROR: {path}: whitespace in repository/tag in {values}")
    entry = (str(repo), str(tag), scope)
    if entry not in seen:
        seen.add(entry)
        print(*entry)
PY
}
# Captured first, so a parser failure stops the script (set -e does
# not see the exit status of a `< <(...)` process substitution).
# (a read loop rather than mapfile: /bin/bash on macOS is 3.2)
PINS_OUT=$(read_pins)
PINNED=()
while IFS= read -r line; do
  [ -n "$line" ] && PINNED+=("$line")
done <<< "$PINS_OUT"

if [ "${#PINNED[@]}" -eq 0 ]; then
  echo "ERROR: could not read the pinned image tags from $VALUES." >&2
  exit 1
fi

echo "Pinned by local-k8s-values.yaml (kept):"
# fields of a PINNED entry "<repository> <tag> <scope>"
f_repo()  { echo "${1%% *}"; }
f_tag()   { local t="${1#* }"; echo "${t%% *}"; }
f_scope() { echo "${1##* }"; }

for p in "${PINNED[@]}"; do
  echo "  $(f_repo "$p"):$(f_tag "$p")"
done
echo ""

repo_is_pinned() { # <repository> <tag>
  local p
  for p in "${PINNED[@]}"; do
    [ "$1" = "$(f_repo "$p")" ] && [ "$2" = "$(f_tag "$p")" ] && return 0
  done
  return 1
}

# SAM_REPOS: every managed repository (registry + prefixed local
# refs). OWN_REPOS: the subset whose BARE local name is ours too.
SAM_REPOS=()
OWN_REPOS=()
for p in "${PINNED[@]}"; do
  r=$(f_repo "$p")
  case " ${SAM_REPOS[*]-} " in *" $r "*) ;; *) SAM_REPOS+=("$r") ;; esac
  if [ "$(f_scope "$p")" = "own" ]; then
    case " ${OWN_REPOS[*]-} " in *" $r "*) ;; *) OWN_REPOS+=("$r") ;; esac
  fi
done

# --- Collect the local Docker images to purge ----------------------
LOCAL_PURGE=()
if [ "$DO_LOCAL" -eq 1 ]; then
  if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    echo "WARNING: docker daemon not reachable -- skipping local cleanup."
    DO_LOCAL=0
  else
    while read -r ref; do
      [ -n "$ref" ] || continue
      case "$ref" in *"<none>"*) continue ;; esac
      # ref is either <repo>:<tag> or $REGISTRY/<repo>:<tag>
      local_tag="${ref##*:}"
      local_repo="${ref%:*}"
      case "$local_repo" in
        "$REGISTRY"/*)
          local_repo="${local_repo#"$REGISTRY"/}"
          managed=" ${SAM_REPOS[*]} " ;;
        *)
          # bare name: only gwe/str -- never postgres, seaweedfs
          # or anything else pulled from Docker Hub.
          managed=" ${OWN_REPOS[*]-} " ;;
      esac
      case "$managed" in
        *" $local_repo "*) ;;
        *) continue ;;
      esac
      repo_is_pinned "$local_repo" "$local_tag" || LOCAL_PURGE+=("$ref")
    done < <(docker images --format '{{.Repository}}:{{.Tag}}')
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

manifest_digest() { # <repository> <tag> -> sha256:... (empty if none)
  reg_curl -o /dev/null -D - \
    -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
    -H 'Accept: application/vnd.oci.image.manifest.v1+json' \
    -H 'Accept: application/vnd.docker.distribution.manifest.list.v2+json' \
    -H 'Accept: application/vnd.oci.image.index.v1+json' \
    "https://$REGISTRY/v2/$1/manifests/$2" 2>/dev/null \
    | tr -d '\r' | awk -F': ' 'tolower($1)=="docker-content-digest"{print $2}'
}

REG_PURGE=()
# " <repo>@<digest> ..." -- the manifests of the pinned tags, checked
# again right before every DELETE.
KEEP_DIGESTS=" "
# Repositories the registry check could not cover (unreadable tag
# list, unresolvable pinned digest). Non-empty -> exit status 1.
REG_UNCHECKED=""
if [ "$DO_REGISTRY" -eq 1 ]; then
  if ! registry_ready; then
    echo "WARNING: no stored credentials for $REGISTRY in"
    echo "  ~/.docker/config.json -- run 'docker login $REGISTRY' to"
    echo "  include the registry in the purge. Skipping it for now."
    DO_REGISTRY=0
    # A missing login is an unchecked registry too, not a clean one.
    REG_UNCHECKED=" ${SAM_REPOS[*]}"
  else
    for repo in "${SAM_REPOS[@]}"; do
      # A failed tag list (401 after a credential change, 5xx,
      # registry down) must not read as "no tags".
      resp=$(reg_curl -w '\n%{http_code}' \
               "https://$REGISTRY/v2/$repo/tags/list" 2>/dev/null || true)
      code="${resp##*$'\n'}"
      body="${resp%$'\n'*}"
      case "$code" in [0-9][0-9][0-9]) ;; *) code="000" ;; esac
      if [ "$code" = "200" ] && tags=$(python3 -c '
import json, sys
d = json.load(sys.stdin)
if not isinstance(d, dict) or d.get("errors") or "tags" not in d:
    sys.exit(1)
print("\n".join(d["tags"] or []))
' 2>/dev/null <<< "$body"); then
        :
      elif [ "$code" = "404" ] && [ "${body#*NAME_UNKNOWN}" != "$body" ]; then
        echo "NOTE: $REGISTRY/$repo does not exist -- nothing to purge there."
        continue
      else
        echo "WARNING: $REGISTRY/$repo not readable (HTTP $code) -- registry NOT checked"
        REG_UNCHECKED+=" $repo"
        continue
      fi
      # Digests of the pinned tags: an unpinned tag that points at
      # the SAME manifest must not be deleted -- a manifest DELETE
      # by digest removes every tag on it, the pinned one included.
      # Fail closed: a pinned digest that cannot be resolved skips
      # the whole repository.
      keep_digests=" "
      skip_repo=0
      while read -r tag; do
        [ -n "$tag" ] || continue
        repo_is_pinned "$repo" "$tag" || continue
        d=$(manifest_digest "$repo" "$tag" || true)
        if [ -z "$d" ]; then
          echo "WARNING: cannot resolve the digest of pinned $repo:$tag --"
          echo "  $repo skipped, nothing purged from it."
          skip_repo=1
          break
        fi
        keep_digests+="$d "
        KEEP_DIGESTS+="$repo@$d "
      done <<< "$tags"
      if [ "$skip_repo" -eq 1 ]; then
        REG_UNCHECKED+=" $repo"
        continue
      fi
      while read -r tag; do
        [ -n "$tag" ] || continue
        repo_is_pinned "$repo" "$tag" && continue
        d=$(manifest_digest "$repo" "$tag" || true)
        if [ -n "$d" ]; then
          case "$keep_digests" in
            *" $d "*)
              echo "NOTE: $repo:$tag shares its manifest with a pinned tag -- kept."
              continue ;;
          esac
        fi
        REG_PURGE+=("$repo:$tag")
      done <<< "$tags"
    done
    [ -z "$REG_UNCHECKED" ] && echo "Registry checked: ${SAM_REPOS[*]}"
  fi
fi

# True (and prints why) if part of the registry was not checked.
registry_unchecked() {
  [ -n "$REG_UNCHECKED" ] || return 1
  echo ""
  echo "WARNING: the registry was NOT checked for:$REG_UNCHECKED"
  echo "  (see the WARNING above) -- unpinned tags there were not"
  echo "  purged. Fix the registry access and re-run."
}

# --- Report --------------------------------------------------------
if [ "${#LOCAL_PURGE[@]}" -eq 0 ] && [ "${#REG_PURGE[@]}" -eq 0 ]; then
  if registry_unchecked; then
    echo "Nothing to purge in what WAS checked."
    exit 1
  fi
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
  registry_unchecked && exit 1
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
DELETED=0
for ref in "${REG_PURGE[@]+"${REG_PURGE[@]}"}"; do
  repo="${ref%:*}"; tag="${ref##*:}"
  digest=$(manifest_digest "$repo" "$tag" || true)

  if [ -z "$digest" ]; then
    echo "WARNING: no digest for $ref -- skipped."
    continue
  fi
  # Re-check against the pinned manifests: the DELETE removes every
  # tag on this digest.
  case "$KEEP_DIGESTS" in
    *" $repo@$digest "*)
      echo "NOTE: $ref shares its manifest with a pinned tag -- kept."
      continue ;;
  esac

  code=$(reg_curl -o /dev/null -w '%{http_code}' -X DELETE \
    "https://$REGISTRY/v2/$repo/manifests/$digest" 2>/dev/null || true)
  case "$code" in
    202|200) echo "Deleted from registry: $ref"
             DELETED=$((DELETED + 1)) ;;
    404)     echo "Already gone from registry: $ref" ;;
    405|501) echo "Registry refuses deletes (HTTP $code) for $ref"
             DELETE_DISABLED=1 ;;
    *)       echo "WARNING: delete of $ref returned HTTP ${code:-000}" ;;
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

if [ "$DELETED" -gt 0 ]; then
  cat <<'EOF'

A manifest DELETE frees no disk space: the layer blobs stay on the
registry-data PVC until the registry's garbage collector runs. Run
it while nothing pushes to the registry, then restart the registry
(its in-memory blob cache still lists the deleted layers, and a
later push would skip uploading them):
  kubectl -n oci exec deploy/registry -- \
    registry garbage-collect /etc/docker/registry/config.yml
  kubectl -n oci rollout restart deploy/registry
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

if registry_unchecked; then
  echo "Image purge INCOMPLETE."
  exit 1
fi
echo ""
echo "Image purge complete."
