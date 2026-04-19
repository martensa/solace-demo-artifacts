#!/bin/sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Deployment defaults ------------------------------------------
SAM_NAMESPACE="sam-solace-lab"
SAM_RELEASE="agent-mesh"

# --- Load environment variables -----------------------------------
if [ -f "$PROJECT_DIR/.env" ]; then
  # shellcheck source=/dev/null
  . "$PROJECT_DIR/.env"
fi

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

# --- Remove Keycloak users, groups, and OIDC client ---------------
echo ""
"$SCRIPT_DIR/teardown-keycloak-users.sh" || true
echo ""
"$SCRIPT_DIR/teardown-keycloak-client.sh" || true

echo ""
echo "Solace Agent Mesh teardown complete."
