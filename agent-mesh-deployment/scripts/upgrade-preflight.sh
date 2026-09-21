#!/bin/bash
set -euo pipefail

# =============================================================
# upgrade-preflight.sh -- compare a new SAM delivery chart with
# the one currently deployed, and validate
# local-k8s-values.yaml against it.
# =============================================================
# The SAM chart ships offline and is not checked in, so a version
# bump cannot be reviewed from the repository alone. This script
# does the review mechanically and prints one report:
#
#   1. Chart.yaml       version / appVersion / dependencies
#   2. Image defaults   the tags the new chart expects (gwe, str,
#                       s3Init, dbInit, postgresql, seaweedfs) --
#                       these are the values to pin in
#                       local-k8s-values.yaml and load-images.sh
#   3. Values schema    every key local-k8s-values.yaml sets,
#                       checked against the new values.schema.json
#                       (the schema is additionalProperties:false,
#                       so an unknown key fails the install)
#   4. Schema diff      keys added / removed between old and new
#   5. Default drift    new chart defaults for the keys we
#                       override (an override may have become
#                       redundant, or newly wrong)
#   6. Package        the image and CLI tarballs sitting next to
#                       the chart, as ready-to-paste .env lines
#   7. helm lint + helm template with our values -- the
#                       authoritative check
#
# Usage:
#   ./upgrade-preflight.sh --new <path> [--old <path>]
#
#   --new   the NEW delivery: its package directory (the chart is
#           found in a subfolder such as Charts/), a packaged chart
#           (.tgz), or an unpacked chart directory
#   --old   the currently deployed delivery, same forms
#           (default: $SAM_CHART_PATH from .env).
#           Omit to skip sections 4 and 5.
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VALUES="$PROJECT_DIR/local-k8s-values.yaml"

NEW_CHART=""
OLD_CHART=""

while [ $# -gt 0 ]; do
  case "$1" in
    --new) NEW_CHART="${2:?--new needs a path}"; shift ;;
    --old) OLD_CHART="${2:?--old needs a path}"; shift ;;
    -h|--help)
      awk '/^# Usage:/{f=1} f && /^# ==/{exit} f' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
  shift
done

if [ -z "$NEW_CHART" ]; then
  echo "ERROR: --new <chart-dir> is required." >&2
  echo "Run with --help for usage." >&2
  exit 1
fi

# Default the old chart to whatever .env currently deploys.
if [ -z "$OLD_CHART" ] && [ -f "$PROJECT_DIR/.env" ]; then
  # shellcheck source=/dev/null
  . "$PROJECT_DIR/.env"
  OLD_CHART="${SAM_CHART_PATH:-}"
fi

# --- Resolve a chart argument to an unpacked directory -------------
# Accepts the unpacked chart directory, a packaged chart (.tgz), or the
# delivery package directory: the package keeps the chart in a
# subfolder (Charts/) next to the image tarballs (Images/), so
# subdirectories are searched as well.
#
# Archives are classified by CONTENT, not by name -- the image
# tarballs are .tar.gz too, so only an archive that really carries a
# Chart.yaml counts as a chart.
SEARCH_DEPTH=3
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

is_chart_archive() { # <file> -- true if the archive holds a Chart.yaml
  # Size-adaptive: a packaged chart is ~100 KB, so its listing is read
  # in full and a Chart.yaml deep in the archive is still found. Only
  # for the multi-GB image tarballs is the listing cut short, which
  # keeps them from being decompressed in full just to classify them.
  #
  # pipefail is off inside the subshell: `grep -q` and `head` close
  # the pipe as soon as they are done, so tar dies of SIGPIPE and
  # would otherwise fail the whole pipeline.
  local size_kb
  size_kb=$(du -k "$1" 2>/dev/null | cut -f1 | tr -d ' ')
  [ -n "$size_kb" ] || size_kb=0
  ( set +o pipefail
    if [ "$size_kb" -lt 51200 ]; then
      tar -tzf "$1" 2>/dev/null | grep -qE '(^|/)Chart\.yaml$'
    else
      tar -tzf "$1" 2>/dev/null | head -400 \
        | grep -qE '(^|/)Chart\.yaml$'
    fi )
}

# Subchart Chart.yaml files live under charts/ and are never the chart
# we are looking for.
find_chart_candidates() { # <dir> -> newline-separated paths
  find "$1" -maxdepth "$SEARCH_DEPTH" -type f -name Chart.yaml 2>/dev/null \
    | grep -v '/charts/' \
    | while IFS= read -r f; do dirname "$f"; done
  find "$1" -maxdepth "$SEARCH_DEPTH" -type f \
    \( -name '*.tgz' -o -name '*.tar.gz' \) 2>/dev/null \
    | while IFS= read -r f; do
        if is_chart_archive "$f"; then printf '%s\n' "$f"; fi
      done
}

unpack_chart() { # <lowercase-label> <archive> -> chart directory
  local label="$1" tgz="$2" dest chart_yaml upper
  upper=$(printf '%s' "$label" | tr '[:lower:]' '[:upper:]')
  dest="$WORK_DIR/$label"
  mkdir -p "$dest"
  tar -xzf "$tgz" -C "$dest"
  chart_yaml=$(find "$dest" -maxdepth 2 -name Chart.yaml \
    | grep -v '/charts/' | head -1)
  if [ -z "$chart_yaml" ]; then
    echo "ERROR: no Chart.yaml inside $tgz." >&2
    return 1
  fi
  echo "Unpacked $upper chart: $tgz" >&2
  dirname "$chart_yaml"
}

resolve_chart() { # <lowercase-label> <path> -> chart directory
  # tr rather than ${label^^}: /bin/bash on macOS is 3.2
  local label="$1" path="$2" upper cands count first
  upper=$(printf '%s' "$label" | tr '[:lower:]' '[:upper:]')

  # Already unpacked?
  if [ -d "$path" ] && [ -f "$path/Chart.yaml" ]; then
    printf '%s\n' "$path"; return 0
  fi

  # A packaged chart named directly?
  if [ -f "$path" ]; then
    if is_chart_archive "$path"; then
      unpack_chart "$label" "$path"
      return $?
    fi
    echo "ERROR: $upper '$path' is not a packaged Helm chart" >&2
    echo "(the archive contains no Chart.yaml)." >&2
    return 1
  fi

  if [ ! -d "$path" ]; then
    echo "ERROR: $upper path '$path' does not exist." >&2
    return 1
  fi

  # A directory to search. (Newline-separated string rather than an
  # array: empty arrays under `set -u` are not safe on bash 3.2, and
  # the package paths contain spaces.)
  cands=$(find_chart_candidates "$path")
  count=$(printf '%s' "$cands" | grep -c . || true)

  if [ "$count" -eq 0 ]; then
    echo "ERROR: no Helm chart under '$path'." >&2
    echo "Searched $SEARCH_DEPTH levels deep for a directory with a" >&2
    echo "Chart.yaml and for archives containing one (image tarballs" >&2
    echo "are recognised by content and skipped)." >&2
    return 1
  fi
  if [ "$count" -gt 1 ]; then
    echo "ERROR: several charts under '$path':" >&2
    printf '%s\n' "$cands" | sed 's/^/  /' >&2
    echo "Point --$label at one of them." >&2
    return 1
  fi

  first=$(printf '%s\n' "$cands" | head -1)
  if [ -d "$first" ]; then
    printf '%s\n' "$first"; return 0
  fi
  unpack_chart "$label" "$first"
}

# Keep the raw argument: if it was the package directory, section 7
# reports the image and CLI tarballs sitting next to the chart.
NEW_INPUT="$NEW_CHART"

NEW_CHART=$(resolve_chart new "$NEW_CHART") || exit 1
if [ -n "$OLD_CHART" ]; then
  OLD_CHART=$(resolve_chart old "$OLD_CHART") || exit 1
fi

[ -f "$VALUES" ] || { echo "ERROR: $VALUES not found." >&2; exit 1; }

# --- Sections 1-5 (python: yaml + json schema walking) -------------
python3 - "$NEW_CHART" "${OLD_CHART:-}" "$VALUES" <<'PY'
import json
import os
import sys

import yaml

new_dir, old_dir, values_path = sys.argv[1], sys.argv[2], sys.argv[3]


def load_yaml(path):
    if not os.path.isfile(path):
        return None
    with open(path) as fh:
        return yaml.safe_load(fh)


def load_json(path):
    if not os.path.isfile(path):
        return None
    with open(path) as fh:
        return json.load(fh)


def rule(title):
    print()
    print(f"== {title}")


# ---------------------------------------------------------------
# 1. Chart metadata
# ---------------------------------------------------------------
new_chart = load_yaml(os.path.join(new_dir, "Chart.yaml")) or {}
old_chart = load_yaml(os.path.join(old_dir, "Chart.yaml")) if old_dir else None

rule("1. Chart metadata")


def deps(chart):
    out = {}
    for d in (chart or {}).get("dependencies") or []:
        out[d.get("alias") or d.get("name")] = d.get("version")
    return out


def show(label, chart):
    if not chart:
        return
    print(f"  {label:5} name={chart.get('name')} "
          f"version={chart.get('version')} "
          f"appVersion={chart.get('appVersion')}")
    for name, ver in sorted(deps(chart).items()):
        print(f"        dependency {name} = {ver}")


show("old", old_chart)
show("new", new_chart)

if old_chart:
    old_deps, new_deps = deps(old_chart), deps(new_chart)
    for name in sorted(set(old_deps) | set(new_deps)):
        if old_deps.get(name) != new_deps.get(name):
            print(f"  CHANGED dependency {name}: "
                  f"{old_deps.get(name, '-')} -> {new_deps.get(name, '-')}")

# ---------------------------------------------------------------
# 2. Image defaults in the new chart
# ---------------------------------------------------------------
new_values = load_yaml(os.path.join(new_dir, "values.yaml")) or {}
old_values = load_yaml(os.path.join(old_dir, "values.yaml")) if old_dir else None


def dig(tree, path):
    cur = tree
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


IMAGE_PATHS = [
    "samDeployment.gwe.image",
    "samDeployment.awe.image",
    "samDeployment.str.image",
    "samDeployment.s3Init.image",
    "samDeployment.dbInit.image",
    "samDoctor.image",
    "persistence-layer.postgresql.image",
    "persistence-layer.seaweedfs.image",
]

rule("2. Image defaults in the NEW chart "
     "(pin these in local-k8s-values.yaml / load-images.sh)")
print(f"  global.imageRegistry default = "
      f"{dig(new_values, 'global.imageRegistry')!r}")
for path in IMAGE_PATHS:
    img = dig(new_values, path)
    if not isinstance(img, dict):
        continue
    ref = "/".join(p for p in (img.get("registry"), img.get("repository")) if p)
    print(f"  {path} = {ref or '<no repository>'}:{img.get('tag')}")
    if old_values:
        old_img = dig(old_values, path)
        if isinstance(old_img, dict) and old_img.get("tag") != img.get("tag"):
            print(f"      was {old_img.get('tag')}")

# ---------------------------------------------------------------
# 3. + 4. Values schema
# ---------------------------------------------------------------
def schema_paths(schema, root=None, prefix="", seen=None):
    """Flatten a JSON schema into dotted property paths."""
    if root is None:
        root = schema
    if seen is None:
        seen = set()
    out = {}
    if not isinstance(schema, dict):
        return out

    if "$ref" in schema:
        ref = schema["$ref"]
        if ref.startswith("#/") and ref not in seen:
            seen = seen | {ref}
            target = root
            for part in ref[2:].split("/"):
                if not isinstance(target, dict) or part not in target:
                    return out
                target = target[part]
            return schema_paths(target, root, prefix, seen)
        return out

    for combiner in ("allOf", "anyOf", "oneOf"):
        for sub in schema.get(combiner) or []:
            out.update(schema_paths(sub, root, prefix, seen))

    props = schema.get("properties")
    if isinstance(props, dict):
        for name, sub in props.items():
            path = f"{prefix}{name}"
            out[path] = sub if isinstance(sub, dict) else {}
            out.update(schema_paths(sub, root, path + ".", seen))

    items = schema.get("items")
    if isinstance(items, dict):
        out.update(schema_paths(items, root, prefix, seen))

    return out


def value_paths(tree, prefix=""):
    """Leaf and intermediate dotted paths actually set in our values."""
    out = []
    if isinstance(tree, dict):
        for name, sub in tree.items():
            path = f"{prefix}{name}"
            out.append(path)
            out.extend(value_paths(sub, path + "."))
    return out


new_schema = load_json(os.path.join(new_dir, "values.schema.json"))
old_schema = load_json(os.path.join(old_dir, "values.schema.json")) if old_dir else None
our_values = load_yaml(values_path) or {}

subchart_roots = set(deps(new_chart)) | set(deps(old_chart or {}))

rule("3. local-k8s-values.yaml against the NEW values.schema.json")
if new_schema is None:
    print("  NOTE: the new chart has no values.schema.json -- unknown keys")
    print("  will not be rejected, but section 6 (helm template) still")
    print("  catches template-level breakage.")
    new_paths = None
else:
    new_paths = schema_paths(new_schema)
    problems = 0
    for path in value_paths(our_values):
        top = path.split(".")[0]
        if path in new_paths:
            continue
        if top in subchart_roots:
            # Subchart values are validated by the subchart's own
            # schema, not by the parent's.
            continue
        # A key under a free-form object (additionalProperties) is fine.
        parent = path.rsplit(".", 1)[0] if "." in path else None
        parent_schema = new_paths.get(parent) if parent else None
        if isinstance(parent_schema, dict) and parent_schema.get(
                "additionalProperties") not in (False, None):
            continue
        print(f"  UNKNOWN KEY: {path}")
        problems += 1
    if problems == 0:
        print("  OK: every key we set exists in the new schema.")
    else:
        print(f"  {problems} key(s) are not in the new schema -- with")
        print("  additionalProperties:false these fail the install.")

    required_missing = []
    for path, sub in sorted(new_paths.items()):
        for req in (sub.get("required") or []) if isinstance(sub, dict) else []:
            child = f"{path}.{req}"
            if dig(our_values, child) is None and dig(new_values, child) is None:
                required_missing.append(child)
    for req in (new_schema.get("required") or []):
        if dig(our_values, req) is None and dig(new_values, req) is None:
            required_missing.append(req)
    if required_missing:
        print("  REQUIRED but unset here and undefaulted by the chart:")
        for path in sorted(set(required_missing)):
            print(f"    {path}")

rule("4. Schema diff old -> new")
if not old_schema or new_paths is None:
    print("  skipped (need values.schema.json in both charts)")
else:
    old_paths = schema_paths(old_schema)
    removed = sorted(set(old_paths) - set(new_paths))
    added = sorted(set(new_paths) - set(old_paths))
    our = set(value_paths(our_values))

    if removed:
        print(f"  REMOVED ({len(removed)}):")
        for path in removed:
            mark = "  <-- WE SET THIS" if path in our else ""
            print(f"    {path}{mark}")
    else:
        print("  REMOVED: none")

    # Added keys are only interesting near what we configure, so show
    # the top two levels in full and the rest collapsed.
    if added:
        print(f"  ADDED ({len(added)}):")
        for path in added:
            print(f"    {path}")
    else:
        print("  ADDED: none")

rule("5. New chart defaults for the keys we override")
if not old_values:
    print("  skipped (need the old chart for the comparison)")
else:
    shown = 0
    for path in value_paths(our_values):
        ours = dig(our_values, path)
        if isinstance(ours, (dict, list)):
            continue
        old_default = dig(old_values, path)
        new_default = dig(new_values, path)
        if old_default == new_default:
            continue
        print(f"  {path}")
        print(f"    chart default: {old_default!r} -> {new_default!r}")
        print(f"    we set:        {ours!r}")
        shown += 1
    if shown == 0:
        print("  No chart default changed for any key we override.")
PY

# --- Section 6: the rest of the delivery package ------------------
# Only meaningful when --new pointed at the package (or a folder in
# it) rather than at a bare chart.
if [ -d "$NEW_INPUT" ]; then
  PKG_LIST="$WORK_DIR/pkg.txt"
  : > "$PKG_LIST"
  find "$NEW_INPUT" -maxdepth "$SEARCH_DEPTH" -type f \
    \( -name '*.tgz' -o -name '*.tar.gz' \) 2>/dev/null | sort \
    | while IFS= read -r f; do
        if is_chart_archive "$f"; then continue; fi
        case "$(basename "$f")" in
          *-app-*) printf 'SAM_APP_IMAGE_TAR=%s\n' "$f" >> "$PKG_LIST" ;;
          *-str-*) printf 'SAM_STR_IMAGE_TAR=%s\n' "$f" >> "$PKG_LIST" ;;
          *-cli-*) printf 'SAM_CLI_TAR=%s\n' "$f" >> "$PKG_LIST" ;;
          *)       printf '# unclassified: %s\n' "$f" >> "$PKG_LIST" ;;
        esac
      done

  if [ -s "$PKG_LIST" ]; then
    echo ""
    echo "== 6. Delivery package artifacts (for .env)"
    sed 's/^/  /' "$PKG_LIST"
    echo ""
    echo "  SAM_CHART_PATH must be an UNPACKED chart directory"
    echo "  (start.sh checks for \$SAM_CHART_PATH/Chart.yaml). If the"
    echo "  package ships the chart packaged, unpack it once:"
    echo "    tar -xzf <chart>.tgz -C <somewhere>"
    echo "  and point SAM_CHART_PATH at the directory that holds"
    echo "  Chart.yaml."
    echo ""
    echo "  Cross-check the versions in these filenames against the"
    echo "  image defaults in section 2 before pinning them in"
    echo "  local-k8s-values.yaml."
  fi
fi

# --- Section 7: helm lint + template ------------------------------
echo ""
echo "== 7. helm lint + helm template with local-k8s-values.yaml"
if ! command -v helm >/dev/null 2>&1; then
  echo "  SKIPPED: helm not found in PATH."
  exit 0
fi

# Stubs for the secrets that start.sh injects via --set. Values are
# irrelevant for rendering; they only have to be non-empty.
STUBS=(
  --set sam.oauthProvider.oidc.issuer=https://auth.example.invalid/realms/x
  --set sam.oauthProvider.oidc.clientId=preflight
  --set sam.oauthProvider.oidc.clientSecret=preflight
  --set llmService.llmServiceApiKey=preflight
)

RENDER_OUT="$WORK_DIR/render.out"

echo "  helm lint ..."
if helm lint "$NEW_CHART" --values "$VALUES" "${STUBS[@]}" \
     > "$RENDER_OUT" 2>&1; then
  echo "  lint OK"
else
  echo "  LINT FAILED:"
  sed 's/^/    /' "$RENDER_OUT"
fi

echo "  helm template ..."
if helm template agent-mesh "$NEW_CHART" \
     --namespace sam-solace-lab \
     --values "$VALUES" "${STUBS[@]}" \
     > "$RENDER_OUT" 2>&1; then
  echo "  template OK -- images that would be pulled:"
  grep -hoE '^\s+image:\s*"?[^"]+"?' "$RENDER_OUT" \
    | sed 's/.*image:[[:space:]]*//; s/"//g' | sort -u | sed 's/^/    /'
else
  echo "  TEMPLATE FAILED:"
  sed 's/^/    /' "$RENDER_OUT"
  echo ""
  echo "  This is the blocking signal: fix local-k8s-values.yaml"
  echo "  until helm template renders, then run start.sh."
fi

cat <<'EOF'

Note: helm template does not evaluate the chart's cluster lookups
(the ingress TLS secret check). Against the live cluster, after the
namespace and the sam-tls certificate exist, the full check is:
  helm upgrade --install agent-mesh <new-chart> \
    -n sam-solace-lab --values local-k8s-values.yaml --dry-run
EOF
