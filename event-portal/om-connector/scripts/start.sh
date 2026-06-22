#!/bin/bash
# Deploy the Solace Event Portal -> OpenMetadata connector into an EXISTING
# OpenMetadata install, via the Helm chart. Idempotent: safe to re-run (helm
# upgrade --install + apply-style secrets). Does NOT touch OM or the cluster
# infrastructure -- it only adds the connector in its own namespace.
#
#   bash scripts/start.sh
#
# Requires a .env (see .env.example) with at least EP_API_TOKEN. The OM
# ingestion-bot JWT is fetched automatically from Keycloak (lab); for a non-lab
# OM set OM_JWT_TOKEN in .env instead.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CHART_DIR="$PROJECT_DIR/charts/solace-eventportal-connector"

# --- Deployment defaults (overridable via .env / env) ----------------------
NAMESPACE="${CONNECTOR_NAMESPACE:-openmetadata-solace-connector}"
RELEASE="${CONNECTOR_RELEASE:-solace-eventportal-connector}"
# Namespace to clone the private-registry pull secret from (lab convention).
PULL_SECRET_SRC_NS="${PULL_SECRET_SRC_NS:-openmetadata-solace-lab}"
PULL_SECRET="${PULL_SECRET:-registry-pull-secret}"
# In-cluster address of the EXISTING OM (used by the connector workloads).
OM_HOST_PORT="${OM_HOST_PORT:-http://openmetadata.openmetadata-solace-lab.svc.cluster.local:8585/api}"
EP_API_URL="${EP_API_URL:-https://api.solace.cloud/api/v2}"
SKIP_INITIAL_INGEST="${SKIP_INITIAL_INGEST:-false}"

# --- CLI prerequisites -----------------------------------------------------
for c in kubectl helm jq; do
  command -v "$c" >/dev/null 2>&1 || { echo "ERROR: $c not found."; exit 1; }
done

# --- Load .env -------------------------------------------------------------
if [ ! -f "$PROJECT_DIR/.env" ]; then
  echo "No .env found. Copy .env.example to .env and set EP_API_TOKEN first:"
  echo "  cp $PROJECT_DIR/.env.example $PROJECT_DIR/.env"
  exit 1
fi
# shellcheck source=/dev/null
set -a; . "$PROJECT_DIR/.env"; set +a

if [ -z "${EP_API_TOKEN:-}" ]; then
  echo "ERROR: EP_API_TOKEN is not set in .env (Event Portal reader token)."
  exit 1
fi

# --- OM ingestion-bot JWT --------------------------------------------------
if [ -n "${OM_JWT_TOKEN:-}" ]; then
  echo "Using OM_JWT_TOKEN from .env."
  BOT_JWT="$OM_JWT_TOKEN"
else
  echo "Fetching OM ingestion-bot JWT from Keycloak ..."
  BOT_JWT="$(bash "$SCRIPT_DIR/get-om-bot-token.sh")"
fi
[ -n "$BOT_JWT" ] || { echo "ERROR: could not obtain OM ingestion-bot JWT."; exit 1; }

# --- Namespace -------------------------------------------------------------
kubectl create namespace "$NAMESPACE" 2>/dev/null || true

# --- Clone the private-registry pull secret (idempotent) -------------------
if kubectl get secret "$PULL_SECRET" -n "$PULL_SECRET_SRC_NS" >/dev/null 2>&1; then
  echo "Cloning $PULL_SECRET from $PULL_SECRET_SRC_NS ..."
  DOCKERCFG=$(kubectl get secret "$PULL_SECRET" -n "$PULL_SECRET_SRC_NS" \
    -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d)
  kubectl create secret generic "$PULL_SECRET" -n "$NAMESPACE" \
    --type=kubernetes.io/dockerconfigjson \
    --from-literal=.dockerconfigjson="$DOCKERCFG" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
else
  echo "WARNING: $PULL_SECRET not found in $PULL_SECRET_SRC_NS -- image pulls may fail."
fi

# --- Connector Secret (tokens kept out of helm values/history) -------------
SECRET_NAME="${RELEASE}-secret"
echo "Creating/updating connector Secret $SECRET_NAME ..."
kubectl create secret generic "$SECRET_NAME" -n "$NAMESPACE" \
  --from-literal=ep-api-token="$EP_API_TOKEN" \
  --from-literal=om-jwt-token="$BOT_JWT" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

# --- Optional scope override (ingestion domain filter + bridge poll scope) --
# EP_DOMAIN_FILTER restricts the import (by domain NAME regex). EP_DOMAIN_IDS
# (comma-separated domain IDs) restricts the bridge's polling to the same scope
# so it never touches OM entities outside the imported domain(s).
HELM_EXTRA=()
if [ -n "${EP_DOMAIN_FILTER:-}" ] || [ -n "${EP_DOMAIN_IDS:-}" ]; then
  OVERRIDE="$(mktemp -t connector-override.XXXXXX.yaml)"
  trap 'rm -f "$OVERRIDE"' EXIT
  : > "$OVERRIDE"
  if [ -n "${EP_DOMAIN_FILTER:-}" ]; then
    printf 'ingestion:\n  filters:\n    domain: %s\n' "'${EP_DOMAIN_FILTER}'" >> "$OVERRIDE"
  fi
  if [ -n "${EP_DOMAIN_IDS:-}" ]; then
    IDS_JSON=$(printf '%s' "$EP_DOMAIN_IDS" | jq -Rc 'split(",")')
    printf 'bridge:\n  pollingDomainIds: %s\n' "$IDS_JSON" >> "$OVERRIDE"
  fi
  HELM_EXTRA+=(-f "$OVERRIDE")
  echo "Scope override:"
  sed 's/^/  /' "$OVERRIDE"
fi

# Force a fresh image pull (use after rebuilding a mutable tag like :0.9.0,
# otherwise nodes keep the cached digest under IfNotPresent).
if [ "${FORCE_PULL:-false}" = "true" ]; then
  HELM_EXTRA+=(--set image.pullPolicy=Always --set ingestion.image.pullPolicy=Always)
  echo "FORCE_PULL=true -> image.pullPolicy=Always"
fi

# --- Helm install / upgrade (runs the bootstrap hook + waits) --------------
echo ""
echo "helm upgrade --install $RELEASE ..."
helm upgrade --install "$RELEASE" "$CHART_DIR" \
  --namespace "$NAMESPACE" \
  --set secret.existingSecret="$SECRET_NAME" \
  --set openMetadata.hostPort="$OM_HOST_PORT" \
  --set eventPortal.apiUrl="$EP_API_URL" \
  ${HELM_EXTRA[@]+"${HELM_EXTRA[@]}"} \
  --wait --timeout 10m

# --- Trigger the initial catalog import ------------------------------------
INGEST_CRON="${RELEASE}-ingestion"
if [ "$SKIP_INITIAL_INGEST" != "true" ] && kubectl get cronjob "$INGEST_CRON" -n "$NAMESPACE" >/dev/null 2>&1; then
  JOB="initial-import-$(date +%s)"
  echo ""
  echo "Triggering initial ingestion (job/$JOB from cronjob/$INGEST_CRON) ..."
  kubectl -n "$NAMESPACE" create job "$JOB" --from=cronjob/"$INGEST_CRON" >/dev/null
  echo "Waiting for the import to finish (up to 15m) ..."
  if kubectl -n "$NAMESPACE" wait --for=condition=complete --timeout=15m job/"$JOB" 2>/dev/null; then
    echo "Initial import complete."
  else
    echo "Initial import not complete yet -- check logs:"
    echo "  kubectl -n $NAMESPACE logs job/$JOB"
  fi
fi

# --- Summary ---------------------------------------------------------------
echo ""
echo "----------------------------------------------------------------"
echo "Connector deployed: release=$RELEASE namespace=$NAMESPACE"
kubectl get pods,cronjobs -n "$NAMESPACE" 2>/dev/null
echo ""
echo "Bridge logs:    kubectl -n $NAMESPACE logs deploy/$RELEASE -f"
echo "Manual import:  kubectl -n $NAMESPACE create job --from=cronjob/$INGEST_CRON manual-\$(date +%s)"
echo "OM UI:          https://openmetadata.solace.lab  (service: ${RELEASE%-connector} -> solace-event-portal)"
echo "----------------------------------------------------------------"
