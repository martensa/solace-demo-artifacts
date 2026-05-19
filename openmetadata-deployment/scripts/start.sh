#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Deployment defaults ------------------------------------------
OM_NAMESPACE="openmetadata-solace-lab"
OM_RELEASE_DEPS="openmetadata-dependencies"
OM_RELEASE_SERVER="openmetadata"
OM_DNS_NAME="openmetadata.solace.lab"
OM_CHART_VERSION="${OM_CHART_VERSION:-1.6.5}"

# --- CLI prerequisites --------------------------------------------
command -v kubectl >/dev/null 2>&1 || { echo "ERROR: kubectl not found."; exit 1; }
command -v helm    >/dev/null 2>&1 || { echo "ERROR: helm not found.";    exit 1; }
command -v jq      >/dev/null 2>&1 || { echo "ERROR: jq not found (brew install jq)."; exit 1; }
command -v openssl >/dev/null 2>&1 || { echo "ERROR: openssl not found."; exit 1; }

# --- CoreDNS NodeHost Helper --------------------------------------
# Idempotentes Hinzufuegen eines Hostname-zu-IP Mappings in die
# CoreDNS NodeHosts ConfigMap (k3s/Rancher Desktop Spezifikum). OM
# selbst macht keine externen Self-Calls, aber die ingestion Workflows
# nutzen `OPENMETADATA_HOST_PORT` und das soll auch von Airflow-Pods
# aus erreichbar bleiben, falls Nutzer den externen Hostname dort
# eintragen.
upsert_coredns_nodehost() {
  local hostname="$1"
  local ip="$2"

  local current new
  current=$(kubectl -n kube-system get configmap coredns \
    -o jsonpath='{.data.NodeHosts}' 2>/dev/null || echo "")

  new=$(printf '%s\n%s %s\n' "$current" "$ip" "$hostname" \
    | awk -v host="$hostname" '
        NF == 0 { next }
        ($2 == host) { next }
        { print }
      ')
  new="${new}"$'\n'"${ip} ${hostname}"

  kubectl -n kube-system patch configmap coredns \
    --type merge \
    -p "$(jq -n --arg nh "$new" '{data:{NodeHosts:$nh}}')" > /dev/null

  kubectl -n kube-system rollout restart deployment coredns > /dev/null
  kubectl -n kube-system rollout status deployment coredns \
    --timeout=60s > /dev/null
}

# --- Helm repo ----------------------------------------------------
echo "Adding open-metadata Helm repo ..."
helm repo add open-metadata https://helm.open-metadata.org/ 2>/dev/null || true
helm repo update open-metadata >/dev/null

# --- Namespace ----------------------------------------------------
kubectl create namespace "$OM_NAMESPACE" 2>/dev/null || true

# --- JWT keypair (idempotent) -------------------------------------
"$SCRIPT_DIR/setup-rsa-keys.sh"

# --- Dependencies (PostgreSQL + OpenSearch + Airflow) -------------
echo ""
echo "Installing/upgrading $OM_RELEASE_DEPS ..."
helm upgrade --install "$OM_RELEASE_DEPS" \
  open-metadata/openmetadata-dependencies \
  --version "$OM_CHART_VERSION" \
  --namespace "$OM_NAMESPACE" \
  --values "$PROJECT_DIR/local-k8s-deps-values.yaml"

echo ""
echo "Waiting for PostgreSQL to be ready ..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=postgresql \
  --namespace "$OM_NAMESPACE" \
  --timeout=300s

echo "Waiting for OpenSearch to be ready ..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=opensearch \
  --namespace "$OM_NAMESPACE" \
  --timeout=300s 2>/dev/null || \
  kubectl wait --for=condition=ready pod \
    -l app=opensearch \
    --namespace "$OM_NAMESPACE" \
    --timeout=300s 2>/dev/null || true

# --- Postgres credentials Secret for OM server --------------------
# The deps Postgres chart creates `openmetadata-postgresql` Secret
# with `postgres-password` and `password`. Server values expect
# `openmetadata-postgres-credentials.postgres-password`. Replicate
# under the expected name (idempotent).
if kubectl get secret openmetadata-postgresql -n "$OM_NAMESPACE" >/dev/null 2>&1; then
  PG_PASSWORD=$(kubectl get secret openmetadata-postgresql -n "$OM_NAMESPACE" \
    -o jsonpath='{.data.password}' | base64 -d)
  kubectl create secret generic openmetadata-postgres-credentials \
    --namespace "$OM_NAMESPACE" \
    --from-literal=postgres-password="$PG_PASSWORD" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
fi

# --- Server -------------------------------------------------------
echo ""
echo "Installing/upgrading $OM_RELEASE_SERVER ..."
helm upgrade --install "$OM_RELEASE_SERVER" \
  open-metadata/openmetadata \
  --version "$OM_CHART_VERSION" \
  --namespace "$OM_NAMESPACE" \
  --values "$PROJECT_DIR/local-k8s-values.yaml"

# --- CoreDNS NodeHosts --------------------------------------------
INGRESS_IP=$(kubectl get svc -n ingress-nginx ingress-nginx-controller \
  -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)
if [ -z "$INGRESS_IP" ]; then
  echo "WARNING: Ingress ClusterIP not resolvable - skipping CoreDNS NodeHosts."
else
  echo ""
  echo "Registering ${OM_DNS_NAME} -> ${INGRESS_IP} in CoreDNS NodeHosts ..."
  upsert_coredns_nodehost "$OM_DNS_NAME" "$INGRESS_IP"
fi

# --- Wait for OM to be ready --------------------------------------
echo ""
echo "Waiting for OpenMetadata server to become ready (boot is slow on first install) ..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/instance="$OM_RELEASE_SERVER" \
  --namespace "$OM_NAMESPACE" \
  --timeout=600s 2>/dev/null || true

echo ""
helm status "$OM_RELEASE_SERVER" --namespace "$OM_NAMESPACE"
echo ""
kubectl get pods --namespace "$OM_NAMESPACE"
echo ""
echo "----------------------------------------------------------------"
echo "OpenMetadata deployment complete."
echo ""
echo "Open https://${OM_DNS_NAME}/signin in a browser. Self-signup with"
echo "    email:    admin@open-metadata.org"
echo "    password: (your choice; >=8 chars, 1 digit, 1 upper, 1 special)"
echo "is granted admin (initialAdmins) because the email principal"
echo "matches admin@open-metadata.org."
echo ""
echo "Ingestion bot JWT:"
echo "  Settings -> Bots -> ingestion-bot -> Token"
echo "Use this token as OM_INGESTION_BOT_TOKEN in your ingestion configs."
echo "----------------------------------------------------------------"
