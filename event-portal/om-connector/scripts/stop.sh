#!/bin/bash
# Remove the Solace Event Portal -> OpenMetadata connector. Idempotent: safe to
# run when nothing (or only part) is deployed.
#
#   bash scripts/stop.sh
#
# This removes the connector workloads + its namespace only. It does NOT delete
# the metadata already imported into OpenMetadata (that is data). To retire the
# imported catalog too, run the bridge soft-delete pass before stopping, or
# delete the `solace-event-portal` service from the OM UI.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

NAMESPACE="${CONNECTOR_NAMESPACE:-openmetadata-solace-connector}"
RELEASE="${CONNECTOR_RELEASE:-solace-eventportal-connector}"
KEEP_NAMESPACE="${KEEP_NAMESPACE:-false}"

for c in kubectl helm; do
  command -v "$c" >/dev/null 2>&1 || { echo "ERROR: $c not found."; exit 1; }
done

# --- Helm uninstall (graceful release teardown) ----------------------------
if helm status "$RELEASE" -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "Uninstalling helm release $RELEASE ..."
  helm uninstall "$RELEASE" -n "$NAMESPACE" --wait || true
else
  echo "Helm release $RELEASE not found in $NAMESPACE -- skipping."
fi

# --- Clean leftover hook / manual Jobs (not always reaped by uninstall) -----
kubectl -n "$NAMESPACE" delete job \
  -l app.kubernetes.io/instance="$RELEASE" --ignore-not-found=true >/dev/null 2>&1 || true

# --- Namespace (removes kubectl-created secrets + any leftovers) ------------
if [ "$KEEP_NAMESPACE" = "true" ]; then
  echo "KEEP_NAMESPACE=true -- leaving namespace $NAMESPACE in place."
  echo "Removing connector-created secrets explicitly ..."
  kubectl -n "$NAMESPACE" delete secret "${RELEASE}-secret" registry-pull-secret \
    --ignore-not-found=true >/dev/null 2>&1 || true
elif kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
  echo "Deleting namespace $NAMESPACE ..."
  kubectl delete namespace "$NAMESPACE" --wait=false
else
  echo "Namespace $NAMESPACE not found -- nothing to delete."
fi

echo ""
echo "Connector removed. The imported metadata remains in OpenMetadata."
echo "To retire it too: bridge soft-delete (--soft-delete-missing) or delete the"
echo "'solace-event-portal' service in the OM UI."
