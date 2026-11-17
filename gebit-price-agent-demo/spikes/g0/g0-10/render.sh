#!/bin/bash
set -euo pipefail
# G0-10: render workflow + entrypoint gpos-spike-ep-p10 into
# spikes/g0/g0-10/.rendered/ and apply (never --prune).
#   ./render.sh [deploy=true|false] [desc-suffix]   render + apply
#   ONLY=1 ./render.sh ...                          render only
HERE="$(cd "$(dirname "$0")" && pwd)"
BSG_ENV="$HERE/../../../../bsg-trading-desk-demo/.env"
[ -f "$BSG_ENV" ] || { echo "ERROR: $BSG_ENV missing" >&2; exit 1; }
# shellcheck disable=SC1090
. "$BSG_ENV"
DEPLOY="${1:-true}"; SUFFIX="${2:-}"
OUT="$HERE/.rendered"
rm -rf "$OUT" && mkdir -p "$OUT/entrypoints" "$OUT/workflows"
cat > "$OUT/manifest.yaml" <<'YAML'
kind: manifest
name: gpos-g0-p10
description: >-
  Gate 0 spike G0-10 of the EuroCIS price agent (broker options).
target:
  name: solace-lab
  url: https://sam.solace.lab
  auth:
    type: oauth
resources:
  workflows:
    - gpos-spike-p10-echo
  entrypoints:
    - gpos-spike-ep-p10
YAML
cp "$HERE/mesh/workflows/gpos-spike-p10-echo.yaml" "$OUT/workflows/"
sed -e "s/__BROKER_USERNAME__/${MQTT_USERNAME}/g" \
    -e "s/__BROKER_PASSWORD__/${MQTT_PASSWORD}/g" \
    -e "s/__DEPLOY__/${DEPLOY}/g" \
    -e "s/__DESC_SUFFIX__/${SUFFIX}/g" \
    "$HERE/mesh/entrypoints/gpos-spike-ep-p10.yaml.template" \
    > "$OUT/entrypoints/gpos-spike-ep-p10.yaml"
chmod 700 "$OUT"; chmod 600 "$OUT/entrypoints/gpos-spike-ep-p10.yaml"
echo "rendered: $OUT (deploy=$DEPLOY)"
[ "${ONLY:-}" = "1" ] && exit 0
cd "$OUT" && "${SAM_CLI_PATH:-sam}" config apply
