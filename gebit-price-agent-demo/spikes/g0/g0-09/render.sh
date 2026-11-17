#!/bin/bash
set -euo pipefail
# Render the G0-09 entrypoint with the broker credentials of the BSG
# demo (.env there) into g0-09/.rendered/ (chmod 600) and apply it.
#   ./render.sh          render + sam config apply
#   ./render.sh --only   render only
HERE="$(cd "$(dirname "$0")" && pwd)"
BSG_ENV="$HERE/../../../../bsg-trading-desk-demo/.env"
[ -f "$BSG_ENV" ] || { echo "ERROR: $BSG_ENV missing" >&2; exit 1; }
# shellcheck disable=SC1090
. "$BSG_ENV"
OUT="$HERE/.rendered"
rm -rf "$OUT" && mkdir -p "$OUT/entrypoints" && chmod 700 "$OUT"
cat > "$OUT/manifest.yaml" <<'YAML'
kind: manifest
name: gpos-g0-p09-entrypoint
description: >-
  Rendered G0-09 spike entrypoint of the EuroCIS price agent (Gate 0).
target:
  name: solace-lab
  url: https://sam.solace.lab
  auth:
    type: oauth
resources:
  entrypoints:
    - gpos-spike-ep-p09
YAML
sed -e "s/__BROKER_USERNAME__/${MQTT_USERNAME}/g" \
    -e "s/__BROKER_PASSWORD__/${MQTT_PASSWORD}/g" \
    "$HERE/mesh/entrypoints/gpos-spike-ep-p09.yaml.template" \
    > "$OUT/entrypoints/gpos-spike-ep-p09.yaml"
chmod 600 "$OUT/entrypoints/gpos-spike-ep-p09.yaml"
echo "rendered: $OUT"
[ "${1:-}" = "--only" ] && exit 0
cd "$OUT" && "${SAM_CLI_PATH:-sam}" config apply
