#!/bin/sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Load environment variables -----------------------------------
if [ -f "$PROJECT_DIR/.env" ]; then
  # shellcheck source=/dev/null
  . "$PROJECT_DIR/.env"
fi

SAM_NAMESPACE="${SAM_NAMESPACE:-sam-ent-k8s}"
SAM_RELEASE="${SAM_RELEASE:-agent-mesh}"

# --- Uninstall Helm release ---------------------------------------
echo "Uninstalling Helm release $SAM_RELEASE ..."
helm uninstall "$SAM_RELEASE" \
  --namespace "$SAM_NAMESPACE" 2>/dev/null || true

# --- Clean up PVCs ------------------------------------------------
echo "Deleting PVCs ..."
kubectl delete pvc \
  -l app.kubernetes.io/instance="$SAM_RELEASE" \
  --namespace "$SAM_NAMESPACE" 2>/dev/null || true

# --- Delete namespace ---------------------------------------------
echo "Deleting namespace $SAM_NAMESPACE ..."
kubectl delete namespace "$SAM_NAMESPACE" 2>/dev/null || true

# --- Remove Keycloak OIDC client ----------------------------------
echo ""
"$SCRIPT_DIR/teardown-keycloak-client.sh" || true

echo ""
echo "Solace Agent Mesh teardown complete."
