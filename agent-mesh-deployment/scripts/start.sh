#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Deployment defaults ------------------------------------------
SAM_NAMESPACE="sam-solace-lab"
SAM_RELEASE="agent-mesh"
SAM_DNS_NAME="sam.solace.lab"
# The SAM v2 chart is distributed offline (not on a public Helm repo)
# and is deliberately NOT checked in. SAM_CHART_PATH in .env points at
# the unpacked chart directory; the chart version is whatever that
# directory contains (no --version pinning against a remote repo).

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
# Idempotentes Hinzufuegen eines Hostname-zu-IP Mappings in die
# CoreDNS NodeHosts ConfigMap (k3s/Rancher Desktop Spezifikum).
# Bestehende Eintraege fuer diesen Hostname werden ersetzt,
# Leerzeilen werden normalisiert.
# -------------------------------------------------------------
upsert_coredns_nodehost() {
  local hostname="$1"
  local ip="$2"

  local current new
  current=$(kubectl -n kube-system get configmap coredns \
    -o jsonpath='{.data.NodeHosts}' 2>/dev/null || echo "")

  new=$(printf '%s\n' "$current" \
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

# --- Load environment variables -----------------------------------
if [ ! -f "$PROJECT_DIR/.env" ]; then
  echo "No .env file found. Copying .env.example to .env ..."
  cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
  echo "Please edit .env with your credentials, then re-run."
  exit 1
fi

# shellcheck source=/dev/null
. "$PROJECT_DIR/.env"

# --- Validate required variables ----------------------------------
missing=""
for var in KEYCLOAK_ISSUER KEYCLOAK_CLIENT_ID KEYCLOAK_CLIENT_SECRET \
           LLM_SERVICE_API_KEY; do
  val="${!var:-}"
  if [ -z "$val" ] || [ "$val" = "changeme" ]; then
    missing="$missing $var"
  fi
done

if [ -n "$missing" ]; then
  echo "ERROR: The following variables in .env are missing or"
  echo "still set to the placeholder value:"
  echo " $missing"
  exit 1
fi

# --- Offline chart path -------------------------------------------
if [ -z "${SAM_CHART_PATH:-}" ] || [ ! -f "$SAM_CHART_PATH/Chart.yaml" ]; then
  echo "ERROR: SAM_CHART_PATH in .env must point at the unpacked"
  echo "SAM v2 Helm chart directory (containing Chart.yaml)."
  echo "Current value: '${SAM_CHART_PATH:-<unset>}'"
  exit 1
fi
CHART_VERSION=$(awk '$1 == "version:" {print $2; exit}' \
  "$SAM_CHART_PATH/Chart.yaml")
echo "Using local chart: $SAM_CHART_PATH (version ${CHART_VERSION:-unknown})"

# --- Observability overlay (metrics) ------------------------------
# scripts/observability/ overlays the image-baked component configs
# with a management_server block (Prometheus /metrics on the health
# ports) via a Helm post-renderer plugin. Guard against vendor
# config drift first, then make sure the plugin is installed.
GWE_IMG=$(python3 -c "
import yaml
v = yaml.safe_load(open('$PROJECT_DIR/local-k8s-values.yaml'))
i = v['samDeployment']['gwe']['image']
print(f\"{i['repository']}:{i['tag']}\")")
STR_IMG=$(python3 -c "
import yaml
v = yaml.safe_load(open('$PROJECT_DIR/local-k8s-values.yaml'))
i = v['samDeployment']['str']['image']
print(f\"{i['repository']}:{i['tag']}\")")
"$PROJECT_DIR/scripts/observability/check-config-drift.sh" \
  "$GWE_IMG" "$STR_IMG"

if ! helm plugin list 2>/dev/null | grep -q "^sam-observability"; then
  echo "Installing helm post-renderer plugin sam-observability ..."
  helm plugin install "$PROJECT_DIR/scripts/observability/helm-plugin"
fi

# --- Namespace and pull secret ------------------------------------
kubectl create namespace "$SAM_NAMESPACE" 2>/dev/null || true

# --- TLS certificate (cert-manager) -------------------------------
# The SAM v2 chart validates at install time (lookup-based, gated by
# validations.clusterResourceChecks) that the ingress TLS secret
# already exists. Provision it explicitly via cert-manager
# (solace-lab-ca-issuer), matching the lab convention used by keycloak,
# grafana, registry and openmetadata. The namespace delete in stop.sh
# cleans up both the Certificate and the generated secret.
echo "Provisioning sam-tls certificate via cert-manager ..."
kubectl apply -f "$PROJECT_DIR/manifests/sam-tls-certificate.yaml"
kubectl wait --for=condition=Ready certificate/sam-tls \
  --namespace "$SAM_NAMESPACE" --timeout=120s

# --- CoreDNS NodeHosts --------------------------------------------
# SAM macht interne Self-Calls ueber die externe URL (OAuth2 flow,
# Platform Service -> WebUI), daher muss sam.solace.lab auch
# cluster-intern auf die Ingress ClusterIP aufloesen.
INGRESS_IP=$(kubectl get svc -n ingress-nginx ingress-nginx-controller \
  -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)

if [ -z "$INGRESS_IP" ]; then
  echo "WARNING: Ingress ClusterIP not resolvable - skipping CoreDNS NodeHosts"
else
  echo "Registering ${SAM_DNS_NAME} -> ${INGRESS_IP} in CoreDNS NodeHosts ..."
  upsert_coredns_nodehost "$SAM_DNS_NAME" "$INGRESS_IP"
fi

# --- Install / Upgrade --------------------------------------------
helm upgrade --install "$SAM_RELEASE" \
  "$SAM_CHART_PATH" \
  --namespace "$SAM_NAMESPACE" \
  --values "$PROJECT_DIR/local-k8s-values.yaml" \
  --set sam.oauthProvider.oidc.issuer="$KEYCLOAK_ISSUER" \
  --set sam.oauthProvider.oidc.clientId="$KEYCLOAK_CLIENT_ID" \
  --set sam.oauthProvider.oidc.clientSecret="$KEYCLOAK_CLIENT_SECRET" \
  --set llmService.llmServiceApiKey="$LLM_SERVICE_API_KEY" \
  --post-renderer sam-observability

# --- Observability manifests (Services, ServiceMonitors,
#     Dashboards, Alerts) ------------------------------------------
kubectl apply -R -f "$PROJECT_DIR/manifests/observability/"

echo ""
echo "Waiting for pods to become ready ..."
PODS_READY=1
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/instance="$SAM_RELEASE" \
  --namespace "$SAM_NAMESPACE" \
  --timeout=300s 2>/dev/null || PODS_READY=0

echo ""
helm status "$SAM_RELEASE" --namespace "$SAM_NAMESPACE"
echo ""
kubectl get pods \
  -l app.kubernetes.io/instance="$SAM_RELEASE" \
  --namespace "$SAM_NAMESPACE"
echo ""
if [ "$PODS_READY" -eq 1 ]; then
  echo "Solace Agent Mesh deployment complete."
else
  echo "Helm install finished, but not all pods became ready within"
  echo "300s. Watch them with:"
  echo "  kubectl get pods -n $SAM_NAMESPACE -w"
fi
