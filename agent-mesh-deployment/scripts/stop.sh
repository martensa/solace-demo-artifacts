#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Deployment defaults ------------------------------------------
SAM_NAMESPACE="sam-solace-lab"
SAM_RELEASE="agent-mesh"
SAM_DNS_NAME="sam.solace.lab"

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
echo "Deleting PVCs ..."
kubectl delete pvc \
  -l app.kubernetes.io/instance="$SAM_RELEASE" \
  --namespace "$SAM_NAMESPACE" 2>/dev/null || true

# --- Delete namespace ---------------------------------------------
echo "Deleting namespace $SAM_NAMESPACE ..."
kubectl delete namespace "$SAM_NAMESPACE" 2>/dev/null || true

# --- Remove CoreDNS NodeHosts entry -------------------------------
echo "Removing ${SAM_DNS_NAME} from CoreDNS NodeHosts ..."
remove_coredns_nodehost "$SAM_DNS_NAME"

# --- Remove Keycloak users, groups, and OIDC client ---------------
echo ""
"$SCRIPT_DIR/teardown-keycloak-users.sh" || true
echo ""
"$SCRIPT_DIR/teardown-keycloak-client.sh" || true

echo ""
echo "Solace Agent Mesh teardown complete."
