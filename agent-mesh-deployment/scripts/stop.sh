#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Deployment defaults ------------------------------------------
SAM_NAMESPACE="sam-solace-lab"
SAM_RELEASE="agent-mesh"
SAM_DNS_NAME="sam.solace.lab"
# Artifacts this deployment creates OUTSIDE $SAM_NAMESPACE. They
# survive the namespace delete and must be removed by name.
MONITORING_NAMESPACE="monitoring"
HELM_PLUGIN="sam-observability"
# sam CLI login cache (macOS path, see scripts/lib/common.sh). The
# Keycloak client teardown below invalidates the cached token.
SAM_AUTH_CACHE="$HOME/Library/Application Support/sam/auth/solace-lab.json"

PURGE_IMAGES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --purge-images)
      PURGE_IMAGES=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: ./stop.sh [--purge-images]

Full teardown of the Solace Agent Mesh deployment: Helm release,
namespace, the observability artifacts in the monitoring namespace,
the Helm post-renderer plugin, local caches, the CoreDNS NodeHosts
entry and the Keycloak client/users.

  --purge-images   also remove SAM container images that
                   local-k8s-values.yaml does not pin, from the
                   local Docker daemon and from registry.solace.lab
                   (see scripts/purge-images.sh)
EOF
      exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
  shift
done

# --- CLI prerequisites --------------------------------------------
command -v kubectl >/dev/null 2>&1 || {
  echo "ERROR: kubectl not found in PATH."; exit 1
}
command -v helm >/dev/null 2>&1 || {
  echo "ERROR: helm not found in PATH."; exit 1
}
command -v jq >/dev/null 2>&1 || {
  echo "ERROR: jq not found in PATH (brew install jq)."; exit 1
}

# -------------------------------------------------------------
# CoreDNS NodeHosts Helper
#
# Idempotentes Entfernen eines Hostname-Eintrags aus der
# CoreDNS NodeHosts ConfigMap. Patcht nur wenn sich wirklich
# etwas aendert, damit CoreDNS nicht unnoetig neugestartet wird.
# -------------------------------------------------------------
remove_coredns_nodehost() {
  local hostname="$1"

  local current new
  current=$(kubectl -n kube-system get configmap coredns \
    -o jsonpath='{.data.NodeHosts}' 2>/dev/null || echo "")

  if [ -z "$current" ]; then
    return 0
  fi

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

# (No .env sourcing here: stop.sh itself uses no .env variables and
# the Keycloak teardown scripts source .env on their own.)

# --- Data-loss notice ---------------------------------------------
echo "NOTE: this teardown deletes the platform database and with it"
echo "ALL DB-managed content: RBAC roles/claim mappings/default roles,"
echo "connectors, skills, agents, workflows, the MCP entrypoint and"
echo "model max_tokens tuning. See 'Rebuilding after teardown' in the"
echo "README for the re-provisioning order."
echo ""

# --- Uninstall Helm release ---------------------------------------
echo "Uninstalling Helm release $SAM_RELEASE ..."
helm uninstall "$SAM_RELEASE" \
  --namespace "$SAM_NAMESPACE" 2>/dev/null || true

# --- Clean up PVCs ------------------------------------------------
# Helm leaves the StatefulSet PVCs (postgresql, seaweedfs) behind;
# the namespace delete below would catch them too, but deleting
# them first keeps the namespace from waiting on volume detach.
echo "Deleting PVCs ..."
kubectl delete pvc --all \
  --namespace "$SAM_NAMESPACE" --timeout=120s 2>/dev/null || true

# --- Delete namespace ---------------------------------------------
echo "Deleting namespace $SAM_NAMESPACE ..."
kubectl delete namespace "$SAM_NAMESPACE" --timeout=180s 2>/dev/null || true

if kubectl get namespace "$SAM_NAMESPACE" >/dev/null 2>&1; then
  echo "WARNING: namespace $SAM_NAMESPACE still exists. It is most"
  echo "likely stuck on a finalizer. Inspect and clear it with:"
  echo "  kubectl get namespace $SAM_NAMESPACE -o yaml"
  echo "  kubectl api-resources --verbs=list --namespaced -o name \\"
  echo "    | xargs -n1 kubectl get -n $SAM_NAMESPACE --ignore-not-found"
fi

# --- Released PersistentVolumes -----------------------------------
# Deleting the PVCs releases the PVs. With the k3s local-path
# default (reclaimPolicy Delete) they vanish on their own; a PV
# created with Retain would linger and keep its host directory.
LEFTOVER_PVS=$(kubectl get pv \
  -o jsonpath="{range .items[?(@.spec.claimRef.namespace=='$SAM_NAMESPACE')]}{.metadata.name}{' '}{end}" \
  2>/dev/null || true)
if [ -n "${LEFTOVER_PVS// /}" ]; then
  echo "Deleting released PersistentVolumes: $LEFTOVER_PVS"
  # shellcheck disable=SC2086
  kubectl delete pv $LEFTOVER_PVS --timeout=120s 2>/dev/null || true
fi

# --- Observability artifacts outside the namespace ----------------
# start.sh applies manifests/observability/ recursively; two of those
# objects live in the monitoring namespace (the Grafana datasource
# sidecar only watches ConfigMaps there, and the lab convention puts
# PrometheusRules there too), so the namespace delete does not
# remove them.
echo "Removing observability artifacts from namespace $MONITORING_NAMESPACE ..."
kubectl delete prometheusrule sam-alerts \
  --namespace "$MONITORING_NAMESPACE" --ignore-not-found 2>/dev/null || true
kubectl delete configmap grafana-datasource-sam-platform-config \
  --namespace "$MONITORING_NAMESPACE" --ignore-not-found 2>/dev/null || true

# --- Helm post-renderer plugin ------------------------------------
# start.sh installs it on demand; it is a host-side artifact and its
# kustomize config bases are pinned to one SAM delivery, so a stale
# copy must not survive into the next version.
if helm plugin list 2>/dev/null | grep -q "^$HELM_PLUGIN"; then
  echo "Uninstalling Helm plugin $HELM_PLUGIN ..."
  helm plugin uninstall "$HELM_PLUGIN" >/dev/null 2>&1 || true
fi

# --- Remove CoreDNS NodeHosts entry -------------------------------
echo "Removing ${SAM_DNS_NAME} from CoreDNS NodeHosts ..."
remove_coredns_nodehost "$SAM_DNS_NAME"

# --- Remove Keycloak users, groups, and OIDC client ---------------
echo ""
"$SCRIPT_DIR/teardown-keycloak-users.sh" || true
echo ""
"$SCRIPT_DIR/teardown-keycloak-client.sh" || true

# --- Local caches -------------------------------------------------
# The extracted sam CLI is version-pinned to the delivery package it
# came from, and the login cache holds a token for the Keycloak
# client just deleted. Both must go so the next install re-creates
# them from the current .env.
if [ -d "$SCRIPT_DIR/lib/.cache" ]; then
  echo ""
  echo "Removing cached sam CLI ($SCRIPT_DIR/lib/.cache) ..."
  rm -rf "$SCRIPT_DIR/lib/.cache"
fi
if [ -d "$SCRIPT_DIR/rbac/.cache" ]; then
  rm -rf "$SCRIPT_DIR/rbac/.cache"
fi
if [ -f "$SAM_AUTH_CACHE" ]; then
  echo "Removing stale sam CLI login cache ..."
  rm -f "$SAM_AUTH_CACHE"
fi

# --- Container images (opt-in) ------------------------------------
if [ "$PURGE_IMAGES" -eq 1 ]; then
  echo ""
  "$SCRIPT_DIR/purge-images.sh" --yes || true
fi

echo ""
echo "Solace Agent Mesh teardown complete."
if [ "$PURGE_IMAGES" -ne 1 ]; then
  echo ""
  echo "Container images were kept. To drop the SAM images that"
  echo "local-k8s-values.yaml no longer pins (local Docker daemon +"
  echo "registry.solace.lab):"
  echo "  ./scripts/purge-images.sh --dry-run   # review"
  echo "  ./scripts/purge-images.sh             # remove"
fi
