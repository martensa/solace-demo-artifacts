#!/bin/bash
set -euo pipefail

# =============================================================
# check-metrics-gate.sh -- does the delivery still honour
# SAM_OBSERVABILITY_ENABLED?
# =============================================================
# Since 2.348.22 each image-baked component config carries an
# env-gated management_server block, and local-k8s-values.yaml
# turns it on with environmentVariables.SAM_OBSERVABILITY_ENABLED.
# Nothing is overlaid any more, so a new delivery cannot be
# silently overridden -- but if it renamed or dropped that gate,
# /metrics would just vanish from Prometheus. This checks the
# three baked configs in the local images and WARNS (exit 0) so
# an upgrade surfaces the change instead of hiding it. Called by
# start.sh before helm.
#
# Usage: check-metrics-gate.sh <gwe-image-ref> <str-image-ref>
# =============================================================

GWE_IMG="${1:?gwe image ref required}"
STR_IMG="${2:?str image ref required}"
GATE='${SAM_OBSERVABILITY_ENABLED'

missing=""
unchecked=""
check() { # <image> <path-in-image> <label>
  local cfg
  # Never pull just for this check (the str image is ~10 GB): an
  # image the local daemon no longer has -- the kubelet image GC
  # removes unused ones -- is reported as unchecked, not as off.
  if ! docker image inspect "$1" >/dev/null 2>&1; then
    unchecked="$unchecked $3($1)"
    return
  fi
  if ! cfg=$(docker run --rm --entrypoint cat "$1" "$2" 2>/dev/null); then
    unchecked="$unchecked $3($1: $2 unreadable)"
    return
  fi
  grep -qF "$GATE" <<<"$cfg" || missing="$missing $3"
}

check "$GWE_IMG" /etc/sam/configs/gwe/gwe.yaml gwe
check "$GWE_IMG" /etc/sam/configs/awe/sam.yaml awe
check "$STR_IMG" /etc/sam/configs/str/str.yaml str

if [ -n "$unchecked" ]; then
  cat >&2 <<EOF
NOTE: metrics gate NOT checked for:$unchecked
  The image is not in the local Docker daemon (./scripts/load-images.sh
  restores it). Deploying anyway -- the pods pull from the registry.
EOF
fi
if [ -n "$missing" ]; then
  cat >&2 <<EOF
WARNING: metrics gate not found in:$missing
  The baked config no longer references SAM_OBSERVABILITY_ENABLED,
  so Prometheus /metrics will stay off for these components. Look
  for the new switch in the management_server block:
    docker run --rm --entrypoint cat <image> /etc/sam/configs/<c>/<file>.yaml
  and update environmentVariables in local-k8s-values.yaml.
  Deploying anyway -- everything but metrics is unaffected.
EOF
  exit 0
fi
[ -z "$unchecked" ] && \
  echo "Metrics gate present in gwe/awe/str configs (SAM_OBSERVABILITY_ENABLED)."
exit 0
