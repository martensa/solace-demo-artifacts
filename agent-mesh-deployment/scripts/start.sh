#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Deployment defaults ------------------------------------------
SAM_NAMESPACE="sam-solace-lab"
SAM_RELEASE="agent-mesh"

# --- CLI prerequisites --------------------------------------------
command -v kubectl >/dev/null 2>&1 || {
  echo "ERROR: kubectl not found in PATH."; exit 1
}
command -v helm >/dev/null 2>&1 || {
  echo "ERROR: helm not found in PATH."; exit 1
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

# --- Helm repo ----------------------------------------------------
helm repo add solace-agent-mesh \
  https://solaceproducts.github.io/solace-agent-mesh-helm-quickstart/ \
  2>/dev/null || true
helm repo update solace-agent-mesh

# --- Namespace and pull secret ------------------------------------
kubectl create namespace "$SAM_NAMESPACE" 2>/dev/null || true

# --- Install / Upgrade --------------------------------------------
helm upgrade --install "$SAM_RELEASE" \
  solace-agent-mesh/solace-agent-mesh \
  --namespace "$SAM_NAMESPACE" \
  --values "$PROJECT_DIR/local-k8s-values.yaml" \
  --set sam.oauthProvider.oidc.issuer="$KEYCLOAK_ISSUER" \
  --set sam.oauthProvider.oidc.clientId="$KEYCLOAK_CLIENT_ID" \
  --set sam.oauthProvider.oidc.clientSecret="$KEYCLOAK_CLIENT_SECRET" \
  --set llmService.llmServiceApiKey="$LLM_SERVICE_API_KEY"

echo ""
echo "Waiting for pods to become ready ..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/instance="$SAM_RELEASE" \
  --namespace "$SAM_NAMESPACE" \
  --timeout=300s 2>/dev/null || true

echo ""
helm status "$SAM_RELEASE" --namespace "$SAM_NAMESPACE"
echo ""
kubectl get pods \
  -l app.kubernetes.io/instance="$SAM_RELEASE" \
  --namespace "$SAM_NAMESPACE"
echo ""
echo "Solace Agent Mesh deployment complete."
