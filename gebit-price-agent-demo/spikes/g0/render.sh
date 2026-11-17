#!/bin/bash
set -euo pipefail
# Render the spike entrypoint with the broker credentials of the BSG
# demo (.env there) into spikes/g0/.rendered/ and apply it.
#   ./render.sh          render + sam config apply
#   ./render.sh --only   render only
HERE="$(cd "$(dirname "$0")" && pwd)"
BSG_ENV="$HERE/../../../bsg-trading-desk-demo/.env"
[ -f "$BSG_ENV" ] || { echo "ERROR: $BSG_ENV missing" >&2; exit 1; }
# shellcheck disable=SC1090
. "$BSG_ENV"
OUT="$HERE/.rendered"
rm -rf "$OUT" && mkdir -p "$OUT/entrypoints"
cat > "$OUT/manifest.yaml" <<'YAML'
kind: manifest
name: gpos-g0-entrypoint
description: >-
  Rendered spike entrypoint of the EuroCIS price agent (Gate 0).
target:
  name: solace-lab
  url: https://sam.solace.lab
  auth:
    type: oauth
resources:
  entrypoints:
    - gpos-spike-events
YAML
sed -e "s/__BROKER_USERNAME__/${MQTT_USERNAME}/g" \
    -e "s/__BROKER_PASSWORD__/${MQTT_PASSWORD}/g" \
    "$HERE/mesh/entrypoints/gpos-spike-events.yaml.template" \
    > "$OUT/entrypoints/gpos-spike-events.yaml"
chmod 600 "$OUT/entrypoints/gpos-spike-events.yaml"
echo "rendered: $OUT"
[ "${1:-}" = "--only" ] && exit 0
cd "$OUT" && "${SAM_CLI_PATH:-sam}" config apply
