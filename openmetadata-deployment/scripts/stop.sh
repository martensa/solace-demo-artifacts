#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

OM_NAMESPACE="openmetadata-solace-lab"
OM_RELEASE_DEPS="openmetadata-dependencies"
OM_RELEASE_SERVER="openmetadata"
OM_DNS_NAME="openmetadata.solace.lab"

command -v kubectl >/dev/null 2>&1 || { echo "ERROR: kubectl not found."; exit 1; }
command -v helm    >/dev/null 2>&1 || { echo "ERROR: helm not found.";    exit 1; }
command -v jq      >/dev/null 2>&1 || { echo "ERROR: jq not found (brew install jq)."; exit 1; }

remove_coredns_nodehost() {
  local hostname="$1"
  local current new
  current=$(kubectl -n kube-system get configmap coredns \
    -o jsonpath='{.data.NodeHosts}' 2>/dev/null || echo "")
  [ -z "$current" ] && return 0
  new=$(echo "$current" | awk -v host="$hostname" '
    NF == 0 { next }
    ($2 == host) { next }
    { print }
  ')
  if [ "$current" != "$new" ]; then
    kubectl -n kube-system patch configmap coredns \
      --type merge \
      -p "$(jq -n --arg nh "$new" '{data:{NodeHosts:$nh}}')" > /dev/null
    kubectl -n kube-system rollout restart deployment coredns > /dev/null
  fi
}

# --- Defensive: kill the chmod helper pod if a previous start.sh
# --- run errored before its own cleanup step.
kubectl delete pod chmod-airflow-volumes -n "$OM_NAMESPACE" \
  --ignore-not-found=true >/dev/null 2>&1 || true

# --- Uninstall server first, then deps ---------------------------
echo "Uninstalling Helm release $OM_RELEASE_SERVER ..."
helm uninstall "$OM_RELEASE_SERVER" --namespace "$OM_NAMESPACE" 2>/dev/null || true

echo "Uninstalling Helm release $OM_RELEASE_DEPS ..."
helm uninstall "$OM_RELEASE_DEPS" --namespace "$OM_NAMESPACE" 2>/dev/null || true

# --- PVCs --------------------------------------------------------
# Both Bitnami sub-charts and the OM ones tag PVCs with the release
# label; deleting the namespace alone leaves orphan PVCs on some
# storage classes, so clean them up explicitly.
echo "Deleting PVCs ..."
kubectl delete pvc --all --namespace "$OM_NAMESPACE" 2>/dev/null || true

# --- Secrets we created manually ---------------------------------
echo "Deleting Secrets created by start.sh ..."
kubectl delete secret openmetadata-jwt-keys -n "$OM_NAMESPACE" 2>/dev/null || true
kubectl delete secret mysql-secrets -n "$OM_NAMESPACE" 2>/dev/null || true
kubectl delete secret airflow-mysql-secrets -n "$OM_NAMESPACE" 2>/dev/null || true
kubectl delete secret airflow-secrets -n "$OM_NAMESPACE" 2>/dev/null || true
kubectl delete secret oidc-secrets -n "$OM_NAMESPACE" 2>/dev/null || true

# --- Static hostPath PVs we pre-bound for Airflow -----------------
# Reclaim policy is Delete, so the PVs go away once their bound PVCs
# are gone (above). Force-delete by name as a safety net in case a
# previous run left them with stale claimRefs in Failed/Released.
echo "Deleting static hostPath PVs ..."
kubectl delete pv openmetadata-dependencies-dags openmetadata-dependencies-logs \
  --ignore-not-found=true 2>/dev/null || true

# --- Namespace ----------------------------------------------------
# Block until the namespace is actually gone -- otherwise a follow-up
# `start.sh` will race the finalizer and fail trying to re-create
# resources in a Terminating namespace.
echo "Deleting namespace $OM_NAMESPACE (waiting for finalizers) ..."
if kubectl get namespace "$OM_NAMESPACE" >/dev/null 2>&1; then
  kubectl delete namespace "$OM_NAMESPACE" --wait=true --timeout=180s \
    2>/dev/null || true
fi

# --- CoreDNS NodeHosts -------------------------------------------
echo "Removing ${OM_DNS_NAME} from CoreDNS NodeHosts ..."
remove_coredns_nodehost "$OM_DNS_NAME"

# --- Keycloak OIDC client ----------------------------------------
echo ""
"$SCRIPT_DIR/teardown-keycloak-client.sh" || true

# --- Final state check -------------------------------------------
# Sanity: every resource the start script creates should now be gone.
# Stale state here usually means a finalizer hung or an external
# controller (e.g. cert-manager Certificate) is still cleaning up.
echo ""
echo "Verifying teardown ..."
LEFTOVERS=""
if kubectl get namespace "$OM_NAMESPACE" >/dev/null 2>&1; then
  LEFTOVERS="$LEFTOVERS\n  - namespace $OM_NAMESPACE still present"
fi
for pv in openmetadata-dependencies-dags openmetadata-dependencies-logs; do
  if kubectl get pv "$pv" >/dev/null 2>&1; then
    LEFTOVERS="$LEFTOVERS\n  - PV $pv still present"
  fi
done

echo ""
if [ -z "$LEFTOVERS" ]; then
  echo "OpenMetadata teardown complete -- no leftovers."
else
  echo "OpenMetadata teardown finished with leftovers:"
  printf '%b\n' "$LEFTOVERS"
  echo ""
  echo "Inspect with:"
  echo "  kubectl get namespace $OM_NAMESPACE -o yaml"
  echo "  kubectl get pv | grep openmetadata"
  exit 1
fi
