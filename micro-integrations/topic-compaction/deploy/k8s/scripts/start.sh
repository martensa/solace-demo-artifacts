#!/usr/bin/env bash
# =============================================================================
# Topic Compaction MI - K8s deploy script (idempotent).
#
# Reads credentials from ../../../.env, renders the Secret template,
# and applies the full manifest set including monitoring artifacts.
# Re-running re-applies (kubectl apply is idempotent by design); a
# config checksum annotation triggers a rollout if the ConfigMap
# content changed.
#
# Usage:
#   ./scripts/start.sh             - full deploy (wait for readiness)
#   ./scripts/start.sh --no-wait   - apply and exit immediately
#   ./scripts/start.sh --no-monitor - skip monitoring artifacts
#
# Prerequisites:
#   - kubectl context pointing at the right cluster
#   - kube-prometheus stack in the monitoring namespace
#   - Secret .env (use .env.example as the template)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
K8S_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_DIR="$(cd "$K8S_DIR/../.." && pwd)"

NAMESPACE="${NAMESPACE:-mi-solace-lab}"
MONITORING_NAMESPACE="${MONITORING_NAMESPACE:-monitoring}"

WAIT="true"
APPLY_MONITORING="true"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-wait) WAIT="false"; shift ;;
    --no-monitor) APPLY_MONITORING="false"; shift ;;
    -h|--help)
      grep "^#" "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
done

step() { printf "\n=== %s ===\n" "$*"; }

# -----------------------------------------------------------------------------
# Prerequisites
# -----------------------------------------------------------------------------
step "Pre-flight checks"

for cmd in kubectl envsubst; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: $cmd is required but not installed." >&2
    exit 1
  fi
done

ENV_FILE="$PROJECT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found." >&2
  echo "  cp $PROJECT_DIR/.env.example $ENV_FILE && \$EDITOR $ENV_FILE"
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

for var in SOLACE_HOST SOLACE_VPN SOLACE_USERNAME SOLACE_PASSWORD \
           MI_USER_NAME MI_USER_PASSWORD \
           MI_ADMIN_NAME MI_ADMIN_PASSWORD; do
  if [ -z "${!var:-}" ]; then
    echo "ERROR: $var is not set in $ENV_FILE" >&2
    exit 1
  fi
done

echo "OK: kubectl context = $(kubectl config current-context)"
echo "OK: target namespace = $NAMESPACE"

# -----------------------------------------------------------------------------
# Namespace + Secret
# -----------------------------------------------------------------------------
step "Namespace + Secret"
kubectl apply -f "$K8S_DIR/00-namespace.yaml"

RENDERED_SECRET="$(mktemp -t topic-compaction-secret.XXXXXX.yaml)"
trap 'rm -f "$RENDERED_SECRET"' EXIT

envsubst < "$K8S_DIR/20-secret.yaml.template" > "$RENDERED_SECRET"
if grep -E '\$\{[A-Z_][A-Z0-9_]*\}' "$RENDERED_SECRET" >/dev/null; then
  echo "ERROR: rendered secret still contains \${...} placeholders." >&2
  echo "Check that all variables are exported in $ENV_FILE."
  exit 1
fi

kubectl apply -f "$RENDERED_SECRET"

# -----------------------------------------------------------------------------
# ConfigMap + checksum annotation
# -----------------------------------------------------------------------------
step "ConfigMap"
kubectl apply -f "$K8S_DIR/10-configmap.yaml"

CONFIG_CHECKSUM="$(sha256sum "$K8S_DIR/10-configmap.yaml" | awk '{print $1}')"

# -----------------------------------------------------------------------------
# Storage + workload
# -----------------------------------------------------------------------------
step "Storage + workload"
kubectl apply -f "$K8S_DIR/30-pvc.yaml"

# Patch the deployment with the current config checksum so a
# ConfigMap change triggers a rollout.
RENDERED_DEPLOYMENT="$(mktemp -t topic-compaction-deployment.XXXXXX.yaml)"
trap 'rm -f "$RENDERED_SECRET" "$RENDERED_DEPLOYMENT"' EXIT
sed "s|PLACEHOLDER|$CONFIG_CHECKSUM|" \
    "$K8S_DIR/40-deployment.yaml" > "$RENDERED_DEPLOYMENT"

kubectl apply -f "$RENDERED_DEPLOYMENT"
kubectl apply -f "$K8S_DIR/50-service.yaml"
kubectl apply -f "$K8S_DIR/60-pdb.yaml"
kubectl apply -f "$K8S_DIR/70-networkpolicy.yaml"

# -----------------------------------------------------------------------------
# Monitoring artifacts (in monitoring namespace)
# -----------------------------------------------------------------------------
if [ "$APPLY_MONITORING" = "true" ]; then
  step "Monitoring artifacts"
  if kubectl get namespace "$MONITORING_NAMESPACE" \
        >/dev/null 2>&1; then
    kubectl apply -f "$K8S_DIR/80-servicemonitor.yaml"
    kubectl apply -f "$K8S_DIR/81-prometheusrule.yaml"
    kubectl apply -f "$K8S_DIR/82-grafana-dashboard.yaml"
    echo
    echo "Grafana dashboard:"
    echo "  Title: 'Topic Compaction MI' (UID: topic-compaction-mi)"
    echo "  The kube-prometheus-stack sidecar should pick it up"
    echo "  within ~30 seconds via the grafana_dashboard=1 label."
  else
    echo "WARN: namespace '$MONITORING_NAMESPACE' not found; "
    echo "      skipping monitoring artifacts. Re-run with the"
    echo "      kube-prometheus stack installed."
  fi
fi

# -----------------------------------------------------------------------------
# Wait for readiness
# -----------------------------------------------------------------------------
if [ "$WAIT" = "true" ]; then
  step "Waiting for rollout"
  kubectl -n "$NAMESPACE" rollout status \
      deployment/topic-compaction-mi --timeout=180s
fi

step "Done"
echo "Topic Compaction MI deployed to $NAMESPACE."
echo
echo "Quick checks:"
echo "  kubectl -n $NAMESPACE get pod,svc,pvc"
echo "  kubectl -n $NAMESPACE logs -l app.kubernetes.io/name=topic-compaction-mi -f"
echo "  kubectl -n $NAMESPACE port-forward svc/topic-compaction-mi 18090:8090"
echo "  curl -u \$MI_ADMIN_NAME:\$MI_ADMIN_PASSWORD http://localhost:18090/api/v1/kv?prefix="
