#!/bin/bash
set -euo pipefail

# =============================================================
# check-config-drift.sh -- guard for the full-file config
# overlays in kustomize/configs/*.base.
# =============================================================
# The overlays REPLACE the image-baked component configs, so a
# new SAM delivery that changes gwe.yaml/sam.yaml/str.yaml would
# silently be overridden by our stale copies. This script
# extracts the baked files from the local images and diffs them
# against the pristine .base copies. On drift it aborts with
# re-basing instructions. Called by start.sh before helm.
#
# Usage: check-config-drift.sh <gwe-image-ref> <str-image-ref>
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIGS="$SCRIPT_DIR/kustomize/configs"

GWE_IMG="${1:?gwe image ref required}"
STR_IMG="${2:?str image ref required}"

extract() { # <image> <path-in-image>
  docker run --rm --entrypoint cat "$1" "$2"
}

fail=0
check() { # <image> <path> <base-file> <label>
  if ! extract "$1" "$2" | diff -q - "$CONFIGS/$3" >/dev/null 2>&1; then
    echo "DRIFT: $4 ($2 im Image != $3)" >&2
    fail=1
  fi
}

check "$GWE_IMG" /etc/sam/configs/gwe/gwe.yaml gwe.yaml.base     "gwe"
check "$GWE_IMG" /etc/sam/configs/awe/sam.yaml awe-sam.yaml.base "awe"
check "$STR_IMG" /etc/sam/configs/str/str.yaml str.yaml.base     "str"

if [ "$fail" -ne 0 ]; then
  cat >&2 <<'EOF'

Config drift detected: the SAM delivery changed a baked config
that scripts/observability overlays in full. Re-base before
deploying:

  1. docker run --rm --entrypoint cat <img> <path> \
       > scripts/observability/kustomize/configs/<file>.base
  2. Review the vendor diff, then re-run start.sh.

The overlay content itself (management_server block) lives in
kustomize/configs/management_server.yaml and is re-appended
automatically.
EOF
  exit 1
fi
echo "Observability config overlays match the delivery images."
