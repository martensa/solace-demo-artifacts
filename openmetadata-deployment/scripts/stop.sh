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
kubectl delete secret openmetadata-jwt-keys -n "$OM_NAMESPACE" 2>/dev/null || true
kubectl delete secret openmetadata-postgres-credentials -n "$OM_NAMESPACE" 2>/dev/null || true

# --- Namespace ----------------------------------------------------
echo "Deleting namespace $OM_NAMESPACE ..."
kubectl delete namespace "$OM_NAMESPACE" 2>/dev/null || true

# --- CoreDNS NodeHosts -------------------------------------------
echo "Removing ${OM_DNS_NAME} from CoreDNS NodeHosts ..."
remove_coredns_nodehost "$OM_DNS_NAME"

echo ""
echo "OpenMetadata teardown complete."
