#!/bin/bash
# install.sh -- idempotent install of the BSG trading desk demo.
#   ./scripts/install.sh k8s    namespace bsg-demo: Secret, ConfigMap,
#                               publisher, watcher, bsg-tools, demo-ui
#   ./scripts/install.sh mesh   SAM: connector, agents, workflow, then
#                               the event-mesh entrypoint (rendered)
#   ./scripts/install.sh all    both (make demo-up)
# Only additive: everything is named bsg-*; nothing existing is
# changed. Remove with ./scripts/uninstall.sh (make uninstall).
set -euo pipefail
. "$(dirname "$0")/lib.sh"

PART="${1:-all}"

install_k8s() {
  echo "== Kubernetes ($NS)"
  kubectl get ns "$NS" >/dev/null 2>&1 || kubectl create ns "$NS"
  : "${MQTT_USERNAME:?set MQTT_USERNAME in .env (see .env.example)}"
  : "${MQTT_PASSWORD:?set MQTT_PASSWORD in .env (see .env.example)}"
  kubectl -n "$NS" create secret generic bsg-broker \
    --from-literal=MQTT_USERNAME="$MQTT_USERNAME" \
    --from-literal=MQTT_PASSWORD="$MQTT_PASSWORD" \
    --dry-run=client -o yaml | kubectl apply -f -
  kubectl apply -k "$DEMO_DIR/k8s"
  # Secret or config changes do not roll pods by themselves.
  kubectl -n "$NS" rollout restart deploy >/dev/null
  for d in feed-watcher feed-publisher bsg-tools demo-ui; do
    kubectl -n "$NS" rollout status "deploy/$d" --timeout=120s
  done
}

install_mesh() {
  echo "== SAM mesh (connector, agents, workflow)"
  if grep -rq "__GATE0__" "$DEMO_DIR/mesh/workflows/"; then
    echo "ERROR: mesh/workflows still contains __GATE0__ placeholders." >&2
    echo "Gate 0 (README) must settle the branch node, the artifact" >&2
    echo "hand-over and the run id against SAM 2.493.0 first." >&2
    exit 2
  fi
  sam_login
  local rc=0
  (cd "$DEMO_DIR/mesh" && "$SAM_CLI" config apply) || rc=$?
  [ "$rc" -ne 0 ] && { echo "ERROR: sam config apply failed ($rc)" >&2; exit 1; }

  echo "== SAM entrypoint bsg-desk-events"
  local wf_id target
  wf_id=$(id_of /api/v1/platform/workflows bsg-alert-triage)
  if [ -z "$wf_id" ]; then
    echo "ERROR: workflow bsg-alert-triage not on the platform after apply" >&2; exit 1
  fi
  # ENTRYPOINT_WORKFLOW_TARGET=name once Gate 0 shows the bug is fixed.
  if [ "${ENTRYPOINT_WORKFLOW_TARGET:-runtime}" = name ]; then
    target=bsg-alert-triage
  else
    target="workflow_${wf_id//-/_}"
  fi
  local out="$DEMO_DIR/mesh/.rendered" tpl="$DEMO_DIR/mesh/entrypoints"
  rm -rf "$out" && mkdir -p "$out/entrypoints"
  sed "s/__WORKFLOW_RUNTIME__/$target/g" "$tpl/manifest.yaml.template" > "$out/manifest.yaml"
  sed -e "s/__WORKFLOW_RUNTIME__/$target/g" \
      -e "s/__BROKER_USERNAME__/${SAM_BROKER_USERNAME:-$MQTT_USERNAME}/g" \
      -e "s/__BROKER_PASSWORD__/${SAM_BROKER_PASSWORD:-$MQTT_PASSWORD}/g" \
      "$tpl/bsg-desk-events.yaml.template" > "$out/entrypoints/bsg-desk-events.yaml"
  echo "   targetWorkflowName -> $target (mesh/.rendered/, git-ignored)"
  (cd "$out" && "$SAM_CLI" config apply)

  if ls "$DEMO_DIR"/observability/*.yaml >/dev/null 2>&1; then
    echo "== Grafana dashboard"
    kubectl apply -f "$DEMO_DIR/observability/"
  fi
}

case "$PART" in
  k8s) install_k8s ;;
  mesh) install_mesh ;;
  all) install_k8s; install_mesh ;;
  *) echo "usage: $0 [k8s|mesh|all]" >&2; exit 2 ;;
esac
echo "== done ($PART)"
