#!/bin/bash
set -euo pipefail

# ===========================================================
# DB Designer -- local Rancher Desktop (k3s) deployment
# Loads the vendor image tarballs into the local docker daemon
# (k3s uses the docker runtime, so no registry is needed), then
# helm-installs the db-designer chart with the Rancher overlay.
# ===========================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"          # the "DB Designer" dir
CHART_DIR="$PROJECT_DIR/charts/db-designer"

NAMESPACE="db-designer"
RELEASE="db-designer"
UI_HOST="db-designer.solace.lab"
API_HOST="db-designer-api.solace.lab"

for c in kubectl helm docker jq; do
  command -v "$c" >/dev/null 2>&1 || { echo "ERROR: $c not found in PATH."; exit 1; }
done

# --- CoreDNS NodeHosts helper (k3s/Rancher Desktop) ---------------
upsert_coredns_nodehost() {
  local hostname="$1" ip="$2" current new
  current=$(kubectl -n kube-system get configmap coredns \
    -o jsonpath='{.data.NodeHosts}' 2>/dev/null || echo "")
  new=$(printf '%s\n%s %s\n' "$current" "$ip" "$hostname" \
    | awk -v host="$hostname" 'NF==0{next} ($2==host){next} {print}')
  new="${new}"$'\n'"${ip} ${hostname}"
  kubectl -n kube-system patch configmap coredns --type merge \
    -p "$(jq -n --arg nh "$new" '{data:{NodeHosts:$nh}}')" >/dev/null
  kubectl -n kube-system rollout restart deployment coredns >/dev/null
  kubectl -n kube-system rollout status deployment coredns --timeout=60s >/dev/null
}

# --- /etc/hosts helper (host-side browser resolution) -------------
# The React UI calls the API from the browser, so BOTH hosts must
# resolve on this machine too (CoreDNS only covers in-cluster).
# Idempotent; tagged with a marker comment so stop.sh can remove it.
add_etc_hosts() {
  local marker="# db-designer"
  local line="127.0.0.1 $UI_HOST $API_HOST $marker"
  if grep -q "$marker\$" /etc/hosts 2>/dev/null; then
    echo "    /etc/hosts entry already present"
    return 0
  fi
  echo "    adding db-designer hosts to /etc/hosts (needs sudo) ..."
  if echo "$line" | sudo tee -a /etc/hosts >/dev/null 2>&1; then
    echo "    added: $line"
  else
    echo "    WARNING: could not update /etc/hosts; add this line manually:"
    echo "      $line"
  fi
  return 0
}

# --- Ensure the vendor images are loaded into docker --------------
ensure_image() {
  local name="$1" tar="$2"
  if docker image inspect "$name:latest" >/dev/null 2>&1; then
    echo "image $name:latest already present"
    return
  fi
  [ -f "$tar" ] || { echo "ERROR: image tar not found: $tar"; exit 1; }
  echo "loading $(basename "$tar") (this is large; amd64 images run under"
  echo "emulation on Apple Silicon) ..."
  docker load -i "$tar"
  if ! docker image inspect "$name:latest" >/dev/null 2>&1; then
    local any; any=$(docker images "$name" --format '{{.Repository}}:{{.Tag}}' | head -1)
    [ -n "$any" ] && docker tag "$any" "$name:latest"
  fi
}

echo "==> Ensuring vendor images are loaded ..."
ensure_image connector_designer_services "$PROJECT_DIR/connector_designer_services.tar"
ensure_image connector_designer_ui       "$PROJECT_DIR/connector_designer_ui.tar"

echo "==> Namespace ..."
kubectl create namespace "$NAMESPACE" 2>/dev/null || true

echo "==> Registering hostnames in CoreDNS NodeHosts ..."
INGRESS_IP=$(kubectl get svc -n ingress-nginx ingress-nginx-controller \
  -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)
if [ -n "$INGRESS_IP" ]; then
  upsert_coredns_nodehost "$UI_HOST" "$INGRESS_IP"
  upsert_coredns_nodehost "$API_HOST" "$INGRESS_IP"
  echo "    $UI_HOST, $API_HOST -> $INGRESS_IP"
else
  echo "WARNING: ingress-nginx ClusterIP not found -- skipping CoreDNS."
fi

echo "==> Registering hostnames for browser access (/etc/hosts) ..."
add_etc_hosts

# --- Optional secret overrides from .env (all demo-defaulted) -----
SET_ARGS=()
if [ -f "$PROJECT_DIR/.env" ]; then
  echo "==> Sourcing secret overrides from .env ..."
  # shellcheck source=/dev/null
  . "$PROJECT_DIR/.env"
  add() { [ -n "${2:-}" ] && SET_ARGS+=(--set "$1=$2"); }
  add secret.postgresPassword       "${POSTGRES_PASSWORD:-}"
  add secret.solaceClientPassword   "${SOLACE_CLIENT_PASSWORD:-}"
  add secret.solaceMgmtPassword     "${SOLACE_MGMT_PASSWORD:-}"
  add secret.appSecretKey           "${SECRET_APP_KEY:-}"
  add secret.appRefreshTokenKey     "${SECRET_REFRESH_KEY:-}"
  add secret.passwordEncryptionKey  "${PASSWORD_ENCRYPTION_KEY:-}"
  add secret.adminUserPassword      "${ADMIN_USER_PASSWORD:-}"
  add secret.solaceApiToken         "${SOLACE_API_TOKEN:-}"
fi

echo "==> helm upgrade --install ..."
helm upgrade --install "$RELEASE" "$CHART_DIR" \
  --namespace "$NAMESPACE" \
  -f "$CHART_DIR/values-rancher.yaml" \
  "${SET_ARGS[@]+"${SET_ARGS[@]}"}"

echo ""
echo "==> Waiting for pods ..."
kubectl -n "$NAMESPACE" rollout status deploy/"$RELEASE"-services --timeout=300s || true
kubectl -n "$NAMESPACE" rollout status deploy/"$RELEASE"-ui --timeout=180s || true

echo ""
kubectl -n "$NAMESPACE" get pods -l app.kubernetes.io/instance="$RELEASE"
echo ""
echo "UI : https://$UI_HOST"
echo "API: https://$API_HOST/health"
