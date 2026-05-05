#!/usr/bin/env bash
# =============================================================================
# Topic Compaction MI - K8s teardown script (idempotent).
#
# Removes the workload, monitoring artifacts, and (optionally) the
# data PVC and namespace. Re-running on an already-empty cluster is
# a no-op.
#
# Usage:
#   ./scripts/stop.sh                  - remove workload + monitoring;
#                                        keep PVC + namespace
#   ./scripts/stop.sh --delete-data    - also delete the PVC (destroys state)
#   ./scripts/stop.sh --delete-namespace
#                                      - also delete the namespace
#                                        (implies --delete-data)
#   ./scripts/stop.sh --no-monitor     - skip monitoring-namespace cleanup
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
K8S_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

NAMESPACE="${NAMESPACE:-mi-solace-lab}"
MONITORING_NAMESPACE="${MONITORING_NAMESPACE:-monitoring}"

DELETE_DATA="false"
DELETE_NAMESPACE="false"
APPLY_MONITORING="true"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --delete-data) DELETE_DATA="true"; shift ;;
    --delete-namespace) DELETE_NAMESPACE="true"; DELETE_DATA="true"; shift ;;
    --no-monitor) APPLY_MONITORING="false"; shift ;;
    -h|--help)
      grep "^#" "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
done

step() { printf "\n=== %s ===\n" "$*"; }

if ! command -v kubectl >/dev/null 2>&1; then
  echo "ERROR: kubectl is required but not installed." >&2
  exit 1
fi

# -----------------------------------------------------------------------------
# Monitoring artifacts (delete first so we stop alerting on a
# disappearing target rather than racing with the workload).
# -----------------------------------------------------------------------------
if [ "$APPLY_MONITORING" = "true" ]; then
  step "Monitoring artifacts"
  kubectl -n "$MONITORING_NAMESPACE" delete --ignore-not-found \
      -f "$K8S_DIR/82-grafana-dashboard.yaml"
  kubectl -n "$MONITORING_NAMESPACE" delete --ignore-not-found \
      -f "$K8S_DIR/81-prometheusrule.yaml"
  kubectl -n "$MONITORING_NAMESPACE" delete --ignore-not-found \
      -f "$K8S_DIR/80-servicemonitor.yaml"
fi

# -----------------------------------------------------------------------------
# Workload + network
# -----------------------------------------------------------------------------
step "Workload + network"
kubectl -n "$NAMESPACE" delete --ignore-not-found \
    -f "$K8S_DIR/70-networkpolicy.yaml"
kubectl -n "$NAMESPACE" delete --ignore-not-found \
    -f "$K8S_DIR/60-pdb.yaml"
kubectl -n "$NAMESPACE" delete --ignore-not-found \
    -f "$K8S_DIR/50-service.yaml"
kubectl -n "$NAMESPACE" delete --ignore-not-found \
    -f "$K8S_DIR/40-deployment.yaml"

# -----------------------------------------------------------------------------
# Config + Secret (always safe to delete)
# -----------------------------------------------------------------------------
step "Config + Secret"
kubectl -n "$NAMESPACE" delete --ignore-not-found \
    configmap topic-compaction-mi-config
kubectl -n "$NAMESPACE" delete --ignore-not-found \
    secret topic-compaction-mi-secret

# -----------------------------------------------------------------------------
# Storage (optional)
# -----------------------------------------------------------------------------
if [ "$DELETE_DATA" = "true" ]; then
  step "PersistentVolumeClaim (data destroy)"
  kubectl -n "$NAMESPACE" delete --ignore-not-found \
      -f "$K8S_DIR/30-pvc.yaml"
else
  step "PersistentVolumeClaim"
  echo "Keeping PVC topic-compaction-mi-data (RocksDB state)."
  echo "Run with --delete-data to destroy it."
fi

# -----------------------------------------------------------------------------
# Namespace (optional)
# -----------------------------------------------------------------------------
if [ "$DELETE_NAMESPACE" = "true" ]; then
  step "Namespace"
  kubectl delete --ignore-not-found namespace "$NAMESPACE"
else
  step "Namespace"
  echo "Keeping namespace $NAMESPACE."
  echo "Run with --delete-namespace to remove it."
fi

step "Done"
echo "Teardown complete."
