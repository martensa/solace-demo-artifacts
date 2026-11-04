#!/bin/bash
# uninstall.sh -- remove everything the BSG demo created, nothing else:
# the SAM resources named bsg-* (entrypoint first, then workflow,
# agents, connector), the Grafana dashboard ConfigMap and the
# namespace bsg-demo. Never uses `sam config apply --prune`.
set -uo pipefail
. "$(dirname "$0")/lib.sh"

echo "== SAM resources"
if sam_login; then
  delete_named entrypoint /api/v1/platform/entrypoints bsg-desk-events
  delete_named workflow /api/v1/platform/workflows bsg-alert-triage
  # bsg-alert-runner is listed although the demo no longer installs it
  # (2.493.0 has tool nodes), so an uninstall also clears an older run.
  for a in bsg-desk-assistant bsg-alert-runner bsg-quote-analyst \
           bsg-market-context bsg-desk-communicator; do
    delete_named agent /api/v1/platform/agents "$a"
  done
  delete_named connector /api/v1/platform/connectors bsg-desk-tools
else
  echo "   WARNING: no sam login -- SAM resources left in place"
fi

echo "== Grafana dashboard"
kubectl delete -f "$DEMO_DIR/observability/" --ignore-not-found 2>/dev/null || true

echo "== Namespace $NS"
kubectl delete ns "$NS" --ignore-not-found --wait=true
rm -rf "$DEMO_DIR/mesh/.rendered"
echo "== uninstalled"
