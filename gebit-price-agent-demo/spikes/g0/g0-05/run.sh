#!/bin/bash
# G0-05: apply the spike package. Secrets come from the .env files into
# the process environment only (never into a file); `sam config apply`
# resolves the placeholders. NEVER --prune.
#   ./run.sh plan | apply
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$HERE/../../../.."
# The LiteLLM key is NOT read any more: variants s1a-s1d and s5 put it
# into tool_config, where the platform API returns it in plain text
# (results/README.md finding 19). They are retired; a fixed dummy keeps
# the placeholder resolvable without a secret.
P05_LLM_KEY="retired-no-key"
# shellcheck disable=SC1091
. "$REPO/bsg-trading-desk-demo/.env"
export P05_LLM_KEY P05_BROKER_USER="$MQTT_USERNAME" P05_BROKER_PASS="$MQTT_PASSWORD" P05_DOLLAR='$'
cd "$HERE/mesh"
case "${1:-plan}" in
  plan) "${SAM_CLI_PATH:-sam}" config plan ;;
  apply) "${SAM_CLI_PATH:-sam}" config apply ;;
esac
