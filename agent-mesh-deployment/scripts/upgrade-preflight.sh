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

# A path that does not exist is almost always a copy/paste artifact
# rather than a quoting problem: the shell hands us one intact
# argument (a broken quote would have made the option parser reject
# the extra words), but the name carries an invisible character -- a
# non-breaking space pasted instead of a space is the classic one --
# or a stray trailing blank. Say which, and point at the sibling
# whose name matches once whitespace and punctuation are ignored.
#
# Glob loops rather than `ls`: these names contain spaces.
fuzzy_key() { # <string> -> letters, digits and dots, lowercased
  printf '%s' "$1" | tr -cd '[:alnum:].' | tr '[:upper:]' '[:lower:]'
}

# Name the invisible difference, so a suggestion that looks identical
# to the input still makes sense.
describe_odd_name() { # <name> -- writes to stderr
  case "$1" in
    *[[:space:]]) echo "    ^ that name ENDS WITH A SPACE, which is why" >&2
                  echo "      it looks identical to what you passed." >&2 ;;
  esac
  case "$1" in
    [[:space:]]*) echo "    ^ that name STARTS WITH A SPACE." >&2 ;;
  esac
  if printf '%s' "$1" | LC_ALL=C grep -q '[^ -~]'; then
    echo "    ^ that name contains a non-ASCII byte (almost" >&2
    echo "      certainly a non-breaking space), so on screen it" >&2
    echo "      looks like a normal space." >&2
  fi
}

# The single entry in the parent directory whose name matches once
# whitespace and punctuation are ignored -- nothing if there is no
# such entry or more than one (never guess between two packages).
find_fuzzy_sibling() { # <path> -> path, or nothing
  local path="$1" parent base norm entry found count
  parent=$(dirname "$path")
  base=$(basename "$path")
  [ -d "$parent" ] || return 0
  norm=$(fuzzy_key "$base")
  [ -n "$norm" ] || return 0
  found=""
  count=0
  for entry in "$parent"/*; do
    [ -e "$entry" ] || continue
    if [ "$(fuzzy_key "$(basename "$entry")")" = "$norm" ]; then
      found="$entry"
      count=$((count + 1))
    fi
  done
  if [ "$count" -eq 1 ]; then
    printf '%s\n' "$found"
  fi
  return 0
}

diagnose_missing_path() { # <lowercase-label> <path>
  local label="$1" path="$2"
  local parent base norm entry name hits shown prefix

  parent=$(dirname "$path")
  base=$(basename "$path")

  echo "ERROR: --$label path does not exist:" >&2
  echo "  $path" >&2
  echo "  The argument arrived as ONE path, so the quoting is fine;" >&2
  echo "  the name itself does not match anything on disk." >&2

  if printf '%s' "$path" | LC_ALL=C grep -q '[^ -~]'; then
    echo "  It contains a non-ASCII byte -- very likely a" >&2
    echo "  non-breaking space where a plain space is expected." >&2
  fi
  case "$path" in
    *' ') echo "  It ends with a space." >&2 ;;
    ' '*) echo "  It starts with a space." >&2 ;;
  esac

  if [ ! -d "$parent" ]; then
    echo "  The parent directory does not exist either:" >&2
    echo "    $parent" >&2
    return 1
  fi

  norm=$(fuzzy_key "$base")
  hits=0
  for entry in "$parent"/*; do
    [ -e "$entry" ] || continue
    name=$(basename "$entry")
    if [ "$(fuzzy_key "$name")" = "$norm" ]; then
      if [ "$hits" -eq 0 ]; then
        echo "  A directory here matches once whitespace and" >&2
        echo "  punctuation are ignored:" >&2
      fi
      hits=$((hits + 1))
      echo "    $name" >&2
      describe_odd_name "$name"
      # A glob avoids reproducing the odd character altogether. The
      # parent stays quoted (it may contain spaces); the basename is
      # left unquoted so the shell expands it -- a glob match is one
      # word even when it contains spaces.
      echo "    Re-run with a glob instead of the literal name:" >&2
      printf '      --%s "%s"/%s\n' "$label" "$parent" \
        "$(printf '%s' "$name" \
           | LC_ALL=C sed 's/[^[:alnum:].]\{1,\}/*/g')" >&2
    fi
  done

  if [ "$hits" -gt 0 ]; then
    return 1
  fi

  prefix=$(printf '%s' "$norm" | cut -c1-3)
  echo "  No similar entry in:" >&2
  echo "    $parent" >&2
  if [ -n "$prefix" ]; then
    shown=0
    echo "  Entries there that start with '$prefix':" >&2
    for entry in "$parent"/*; do
      [ -e "$entry" ] || continue
      if [ "$shown" -ge 10 ]; then
        echo "    ..." >&2
        break
      fi
      name=$(basename "$entry")
      case "$(fuzzy_key "$name")" in
        "$prefix"*)
          echo "    $name" >&2
          shown=$((shown + 1)) ;;
      esac
    done
    if [ "$shown" -eq 0 ]; then
      echo "    (none) -- what is actually there:" >&2
      for entry in "$parent"/*; do
        [ -e "$entry" ] || continue
        if [ "$shown" -ge 10 ]; then
          echo "    ..." >&2
          break
        fi
        echo "    $(basename "$entry")" >&2
        shown=$((shown + 1))
      done
    fi
  fi
  return 1
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

  if [ ! -e "$path" ] && [ ! -L "$path" ]; then
    diagnose_missing_path "$label" "$path"
    return 1
  fi

  if [ ! -d "$path" ]; then
    echo "ERROR: $upper path '$path' exists but is neither a" >&2
    echo "directory nor a readable regular file (broken symlink?)." >&2
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

# A path that does not exist, but has exactly one near miss in the
# same directory, is corrected here -- before anything else reads the
# argument. Loud, because it is not the path that was asked for, and
# safe, because this script only reads. Correcting it up front keeps
# the package scan (section 6) pointed at the real directory too.
normalize_path() { # <lowercase-label> <path> -> an existing path
  local label="$1" path="$2" corrected
  if [ -e "$path" ] || [ -L "$path" ]; then
    printf '%s\n' "$path"; return 0
  fi
  corrected=$(find_fuzzy_sibling "$path")
  if [ -z "$corrected" ]; then
    # Leave it be; resolve_chart diagnoses it properly.
    printf '%s\n' "$path"; return 0
  fi
  echo "NOTE: --$label does not exist as given:" >&2
  echo "    $path" >&2
  echo "  but exactly one entry in $(dirname "$path") matches it" >&2
  echo "  once whitespace and punctuation are ignored:" >&2
  echo "    $corrected" >&2
  describe_odd_name "$(basename "$corrected")"
  echo "  Continuing with that path." >&2
  printf '%s\n' "$corrected"
}

NEW_CHART=$(normalize_path new "$NEW_CHART")
if [ -n "$OLD_CHART" ]; then
  OLD_CHART=$(normalize_path old "$OLD_CHART")
fi

# Keep the (normalized) argument: if it was the package directory,
# section 6 reports the image and CLI tarballs next to the chart.
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
          f"appVersion={chart.get('appVersion') or '-'}")
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

def resolve_schema(schema, root, seen=None):
    """Follow $ref and fold allOf into one concrete schema."""
    if not isinstance(schema, dict):
        return {"properties": {}, "additionalProperties": None, "required": []}
    if seen is None:
        seen = frozenset()
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref.startswith("#/") and ref not in seen:
            target = root
            for part in ref[2:].split("/"):
                if not isinstance(target, dict) or part not in target:
                    break
                target = target[part]
            else:
                return resolve_schema(target, root, seen | {ref})
        return {"properties": {}, "additionalProperties": None, "required": []}

    props, addl, req = {}, None, list(schema.get("required") or [])
    for sub in schema.get("allOf") or []:
        r = resolve_schema(sub, root, seen)
        props.update(r["properties"])
        req.extend(r["required"])
        if r["additionalProperties"] is not None:
            addl = r["additionalProperties"]
    props.update(schema.get("properties") or {})
    if schema.get("additionalProperties") is not None:
        addl = schema["additionalProperties"]
    return {"properties": props, "additionalProperties": addl, "required": req}


def validate_values(value, schema, root, prefix, unknown, missing,
                    subchart_roots, chart_defaults, depth=0):
    """Walk OUR values against the schema.

    Only a node that explicitly says additionalProperties:false can
    make a key unknown -- an absent additionalProperties means the
    JSON Schema default, which is PERMISSIVE. Free-form maps such as
    ingress.annotations live there, and their keys contain dots of
    their own, so they must never be split into paths.

    anyOf/oneOf nodes are left alone: validating a choice properly is
    the installer's job, and a false alarm here is worse than a miss
    (section 7 renders the chart for real).
    """
    if not isinstance(schema, dict):
        return
    if schema.get("anyOf") or schema.get("oneOf"):
        return

    r = resolve_schema(schema, root)
    props, addl = r["properties"], r["additionalProperties"]

    for name in r["required"]:
        path = f"{prefix}{name}" if prefix else name
        if isinstance(value, dict) and name in value:
            continue
        if dig(chart_defaults, path) is None:
            missing.append(path)

    if not isinstance(value, dict):
        return

    for name, sub_value in value.items():
        path = f"{prefix}{name}" if prefix else name
        if depth == 0 and name in subchart_roots:
            # Validated by the subchart's own schema, not this one.
            continue
        if name in props:
            validate_values(sub_value, props[name], root, path + ".",
                            unknown, missing, subchart_roots,
                            chart_defaults, depth + 1)
        elif addl is False:
            unknown.append(path)


rule("3. local-k8s-values.yaml against the NEW values.schema.json")
if new_schema is None:
    print("  NOTE: the new chart has no values.schema.json -- unknown keys")
    print("  will not be rejected, but section 7 (helm template) still")
    print("  catches template-level breakage.")
    new_paths = None
else:
    new_paths = schema_paths(new_schema)
    unknown, missing = [], []
    validate_values(our_values, new_schema, new_schema, "",
                    unknown, missing, subchart_roots, new_values)
    if unknown:
        for path in unknown:
            print(f"  UNKNOWN KEY: {path}")
        print(f"  {len(unknown)} key(s) sit under a node that forbids")
        print("  additional properties -- these fail the install.")
    else:
        print("  OK: every key we set is accepted by the new schema.")

    if missing:
        print("  REQUIRED but unset here and undefaulted by the chart:")
        for path in sorted(set(missing)):
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
        # Quoted: .env is SOURCED by start.sh, and these paths
        # routinely contain spaces (the package directory name).
        case "$(basename "$f")" in
          *-app-*) printf 'SAM_APP_IMAGE_TAR="%s"\n' "$f" >> "$PKG_LIST" ;;
          *-str-*) printf 'SAM_STR_IMAGE_TAR="%s"\n' "$f" >> "$PKG_LIST" ;;
          *-cli-*) printf 'SAM_CLI_TAR="%s"\n' "$f" >> "$PKG_LIST" ;;
          postgres-*|seaweedfs-*)
                   printf '# bundled persistence image: %s\n' "$f" \
                     >> "$PKG_LIST" ;;
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

    if grep -q '^# bundled persistence image' "$PKG_LIST"; then
      echo ""
      echo "  The bundled persistence images (postgres, seaweedfs) are"
      echo "  NOT loaded here: global.imageRegistry is \"\" and those"
      echo "  images are pulled from Docker Hub. They matter only for"
      echo "  an air-gapped install -- which would also let the chart"
      echo "  default tag seaweedfs:3.97-compliant be used instead of"
      echo "  the 3.97 override, since that build ships in the package."
    fi

    if ! grep -q '^SAM_CLI_TAR=' "$PKG_LIST"; then
      echo ""
      echo "  No sam CLI tarball in this package -- install the CLI"
      echo "  separately and make sure .env does not still point"
      echo "  SAM_CLI_PATH at the previous version: it takes"
      echo "  precedence over the sam on your PATH (see"
      echo "  scripts/lib/common.sh), so a stale entry silently keeps"
      echo "  using the old CLI."
    fi
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
