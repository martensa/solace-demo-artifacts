#!/bin/bash
set -euo pipefail

# ===========================================================
# DB Designer -- teardown (local Rancher Desktop / k3s)
# Uninstalls the release, deletes the namespace (removing PVCs),
# and cleans up the CoreDNS NodeHosts entries.
# ===========================================================

NAMESPACE="db-designer"
RELEASE="db-designer"
UI_HOST="db-designer.solace.lab"
API_HOST="db-designer-api.solace.lab"

for c in kubectl helm jq; do
  command -v "$c" >/dev/null 2>&1 || { echo "ERROR: $c not found in PATH."; exit 1; }
done

remove_coredns_nodehost() {
  local hostname="$1" current new
  current=$(kubectl -n kube-system get configmap coredns \
    -o jsonpath='{.data.NodeHosts}' 2>/dev/null || echo "")
  [ -z "$current" ] && return
  new=$(printf '%s\n' "$current" \
    | awk -v host="$hostname" 'NF==0{next} ($2==host){next} {print}')
  kubectl -n kube-system patch configmap coredns --type merge \
    -p "$(jq -n --arg nh "$new" '{data:{NodeHosts:$nh}}')" >/dev/null
  kubectl -n kube-system rollout restart deployment coredns >/dev/null
}

remove_etc_hosts() {
  local marker="# db-designer"
  grep -q "$marker\$" /etc/hosts 2>/dev/null || return 0
  echo "==> Removing db-designer entries from /etc/hosts (needs sudo) ..."
  if [[ "$OSTYPE" == darwin* ]]; then
    sudo sed -i '' "/$marker\$/d" /etc/hosts 2>/dev/null \
      || echo "  WARNING: could not edit /etc/hosts"
  else
    sudo sed -i "/$marker\$/d" /etc/hosts 2>/dev/null \
      || echo "  WARNING: could not edit /etc/hosts"
  fi
  return 0
}

echo "==> helm uninstall ..."
helm uninstall "$RELEASE" --namespace "$NAMESPACE" 2>/dev/null || true

echo "==> Deleting namespace $NAMESPACE (removes PVCs) ..."
kubectl delete namespace "$NAMESPACE" --wait=false 2>/dev/null || true

echo "==> Cleaning CoreDNS NodeHosts ..."
remove_coredns_nodehost "$UI_HOST" || true
remove_coredns_nodehost "$API_HOST" || true

remove_etc_hosts

echo "Done. (Docker images are left loaded; remove with"
echo " 'docker rmi connector_designer_services connector_designer_ui' if desired.)"
