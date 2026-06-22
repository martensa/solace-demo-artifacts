#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Deployment defaults ------------------------------------------
OM_NAMESPACE="openmetadata-solace-lab"
OM_RELEASE_DEPS="openmetadata-dependencies"
OM_RELEASE_SERVER="openmetadata"
OM_DNS_NAME="openmetadata.solace.lab"
OM_CHART_VERSION="${OM_CHART_VERSION:-1.13.0}"

# --- CLI prerequisites --------------------------------------------
command -v kubectl >/dev/null 2>&1 || { echo "ERROR: kubectl not found."; exit 1; }
command -v helm    >/dev/null 2>&1 || { echo "ERROR: helm not found.";    exit 1; }
command -v jq      >/dev/null 2>&1 || { echo "ERROR: jq not found (brew install jq)."; exit 1; }
command -v openssl >/dev/null 2>&1 || { echo "ERROR: openssl not found."; exit 1; }

# --- Load environment variables -----------------------------------
if [ ! -f "$PROJECT_DIR/.env" ]; then
  echo "No .env file found. Copying .env.example to .env ..."
  cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
fi

# shellcheck source=/dev/null
. "$PROJECT_DIR/.env"

# --- Validate Keycloak admin creds (needed for client setup) ------
# The client itself is bootstrapped automatically below, but the
# realm admin creds are non-default per deployment so they have to
# come from .env.
for var in KEYCLOAK_URL KEYCLOAK_REALM KEYCLOAK_ADMIN_USER KEYCLOAK_ADMIN_PASSWORD KEYCLOAK_CLIENT_ID KEYCLOAK_ISSUER; do
  val="${!var:-}"
  if [ -z "$val" ] || [ "$val" = "changeme" ]; then
    echo "ERROR: $var is missing or still 'changeme' in .env. Set it before re-running."
    exit 1
  fi
done

# --- Ensure the Keycloak OIDC client exists (idempotent) ----------
# setup-keycloak-client.sh is idempotent: if the client is already
# there it just fetches the secret; if not, it creates one. Capture
# the printed `KEYCLOAK_CLIENT_SECRET=...` line and persist the value
# back into .env so a stop.sh -> start.sh round-trip recovers without
# manual intervention (stop.sh deletes the client; start.sh re-creates
# it and the new server-side secret replaces the stale .env entry).
echo ""
echo "Ensuring Keycloak OIDC client exists ..."
SETUP_OUTPUT=$("$SCRIPT_DIR/setup-keycloak-client.sh")
echo "$SETUP_OUTPUT" | grep -vE '^Set this|^  KEYCLOAK_CLIENT_SECRET='
NEW_CLIENT_SECRET=$(printf '%s\n' "$SETUP_OUTPUT" \
  | grep -oE 'KEYCLOAK_CLIENT_SECRET=[A-Za-z0-9._-]+' \
  | tail -1 \
  | cut -d= -f2-)

if [ -z "$NEW_CLIENT_SECRET" ]; then
  echo "ERROR: Could not extract client secret from setup-keycloak-client.sh output."
  exit 1
fi

if [ "$NEW_CLIENT_SECRET" != "${KEYCLOAK_CLIENT_SECRET:-}" ]; then
  echo "Persisting refreshed KEYCLOAK_CLIENT_SECRET to .env ..."
  if grep -q '^KEYCLOAK_CLIENT_SECRET=' "$PROJECT_DIR/.env"; then
    if [ "$(uname)" = "Darwin" ]; then
      sed -i '' "s|^KEYCLOAK_CLIENT_SECRET=.*$|KEYCLOAK_CLIENT_SECRET=${NEW_CLIENT_SECRET}|" \
        "$PROJECT_DIR/.env"
    else
      sed -i "s|^KEYCLOAK_CLIENT_SECRET=.*$|KEYCLOAK_CLIENT_SECRET=${NEW_CLIENT_SECRET}|" \
        "$PROJECT_DIR/.env"
    fi
  else
    echo "KEYCLOAK_CLIENT_SECRET=${NEW_CLIENT_SECRET}" >> "$PROJECT_DIR/.env"
  fi
fi
KEYCLOAK_CLIENT_SECRET="$NEW_CLIENT_SECRET"

# --- CoreDNS NodeHost Helper --------------------------------------
# Idempotently add a hostname -> IP mapping to the k3s CoreDNS
# NodeHosts ConfigMap so the external hostname also resolves
# in-cluster (relevant for any Airflow workflow that reaches OM via
# OPENMETADATA_HOST_PORT using the external name).
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

# --- DB / pipeline credential Secrets -----------------------------
# Names and keys follow the upstream OM local-Kubernetes quickstart so
# the chart-default password lookups also resolve. The deps chart's
# MySQL initdbScripts seed two databases with these hardcoded demo
# creds; rotating means re-seeding MySQL by hand because initdbScripts
# only run on a fresh data PVC.
#   mysql-secrets.openmetadata-mysql-password    -> openmetadata_db
#   airflow-mysql-secrets.airflow-mysql-password -> airflow_db
#   airflow-secrets.openmetadata-airflow-password -> Airflow admin user
echo ""
echo "Creating/updating MySQL + Airflow credential Secrets ..."
kubectl create secret generic mysql-secrets \
  --namespace "$OM_NAMESPACE" \
  --from-literal=openmetadata-mysql-password="openmetadata_password" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl create secret generic airflow-mysql-secrets \
  --namespace "$OM_NAMESPACE" \
  --from-literal=airflow-mysql-password="airflow_pass" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl create secret generic airflow-secrets \
  --namespace "$OM_NAMESPACE" \
  --from-literal=openmetadata-airflow-password="admin" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

# --- Airflow shared volumes ---------------------------------------
# Rancher Desktop's local-path provisioner refuses to provision RWX
# PVCs, but the Airflow subchart insists on RWX for its dags/ and
# logs/ directories. Workaround: pre-bind two static hostPath PVs
# (RWX, DirectoryOrCreate so the path materialises on first mount).
# The openmetadata-dependencies chart will create matching PVCs
# (name pattern `<release>-dags|-logs`) that bind to these PVs via
# the claimRef set below. Single-node only -- the host path lives on
# the lima VM filesystem.
#
# Note (Wave 0 / OM 1.11.x): we used to also pre-create the PVCs
# here, but chart 1.11.x' server-side-apply field-manager refuses
# to overwrite a client-side-applied PVC. Letting the chart create
# the PVCs avoids the conflict; the chmod step has been moved to
# AFTER `helm install` (see below).
echo ""
echo "Pre-binding hostPath PVs for Airflow dags + logs ..."
kubectl apply -f - <<EOF >/dev/null
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: openmetadata-dependencies-dags
spec:
  capacity:
    storage: 5Gi
  accessModes: ["ReadWriteMany"]
  persistentVolumeReclaimPolicy: Delete
  storageClassName: ""
  hostPath:
    path: /var/openmetadata-dependencies/dags
    type: DirectoryOrCreate
  claimRef:
    namespace: ${OM_NAMESPACE}
    name: openmetadata-dependencies-dags
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: openmetadata-dependencies-logs
spec:
  capacity:
    storage: 5Gi
  accessModes: ["ReadWriteMany"]
  persistentVolumeReclaimPolicy: Delete
  storageClassName: ""
  hostPath:
    path: /var/openmetadata-dependencies/logs
    type: DirectoryOrCreate
  claimRef:
    namespace: ${OM_NAMESPACE}
    name: openmetadata-dependencies-logs
EOF

# --- Dependencies (MySQL + OpenSearch + Airflow) ------------------
echo ""
echo "Installing/upgrading $OM_RELEASE_DEPS ..."
helm upgrade --install "$OM_RELEASE_DEPS" \
  open-metadata/openmetadata-dependencies \
  --version "$OM_CHART_VERSION" \
  --namespace "$OM_NAMESPACE" \
  --values "$PROJECT_DIR/local-k8s-deps-values.yaml"

# --- Permissive mode on Airflow hostPath volumes ------------------
# The kubelet creates DirectoryOrCreate hostPath dirs as 0755 root:root
# and only chgrp's them via fsGroup (no chmod). The Airflow containers
# run as UID 50000 with supplementary group 0 and need WRITE -- so
# chmod the volumes 0777 once via a privileged pod that mounts the
# chart-created PVCs. Runs AFTER helm install so the PVCs exist; airflow
# pods may CrashLoop briefly until chmod completes, then auto-recover
# (we force a restart at the end to avoid waiting for backoff).
echo ""
echo "Waiting for Airflow PVCs to be bound by chart ..."
for pvc in openmetadata-dependencies-dags openmetadata-dependencies-logs; do
  until [ "$(kubectl get pvc "$pvc" -n "$OM_NAMESPACE" \
    -o jsonpath='{.status.phase}' 2>/dev/null)" = "Bound" ]; do
    sleep 2
  done
done

echo "Setting permissive mode on Airflow hostPath volumes ..."
kubectl delete pod chmod-airflow-volumes -n "$OM_NAMESPACE" \
  --ignore-not-found=true >/dev/null
kubectl apply -f - <<EOF >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: chmod-airflow-volumes
  namespace: ${OM_NAMESPACE}
spec:
  restartPolicy: Never
  containers:
    - name: chmod
      image: busybox:1.36
      command: ["sh", "-c", "chmod -R 0777 /dags /logs && echo done"]
      volumeMounts:
        - name: dags
          mountPath: /dags
        - name: logs
          mountPath: /logs
  volumes:
    - name: dags
      persistentVolumeClaim:
        claimName: openmetadata-dependencies-dags
    - name: logs
      persistentVolumeClaim:
        claimName: openmetadata-dependencies-logs
EOF
kubectl wait --for=jsonpath='{.status.phase}'=Succeeded \
  pod/chmod-airflow-volumes -n "$OM_NAMESPACE" --timeout=60s >/dev/null
kubectl delete pod chmod-airflow-volumes -n "$OM_NAMESPACE" >/dev/null

# Force-restart any airflow pods that crash-looped while waiting on
# the permissions fix. They will mount the now-writable volumes cleanly.
echo "Restarting Airflow pods to pick up writable volumes ..."
kubectl delete pods -n "$OM_NAMESPACE" \
  -l 'app.kubernetes.io/name=airflow' --force --grace-period=0 \
  >/dev/null 2>&1 || true

# StatefulSets are created asynchronously by helm install -- wait
# for the resource itself to exist before calling rollout status,
# otherwise it errors with "no matching resources found".
echo ""
echo "Waiting for MySQL StatefulSet to be created ..."
until kubectl get statefulset mysql -n "$OM_NAMESPACE" >/dev/null 2>&1; do
  sleep 2
done
echo "Waiting for MySQL to be ready ..."
kubectl rollout status statefulset/mysql \
  --namespace "$OM_NAMESPACE" --timeout=300s

echo "Waiting for OpenSearch StatefulSet to be created ..."
until kubectl get statefulset opensearch -n "$OM_NAMESPACE" >/dev/null 2>&1; do
  sleep 2
done
echo "Waiting for OpenSearch to be ready ..."
kubectl rollout status statefulset/opensearch \
  --namespace "$OM_NAMESPACE" --timeout=300s || true

# Airflow API server is what OM contacts for pipeline registration.
# Wait for the deployment to settle so the server's first contact
# attempt succeeds; the others (scheduler, dag-processor, triggerer)
# share the same gating since they all share the dags+logs volumes.
# Note (Wave 0 / OM 1.11.x): chart 1.11.x renamed the airflow web
# deployment to `api-server` (matches Airflow 3.x's REST API plane).
echo "Waiting for Airflow api-server deployment to be ready ..."
until kubectl get deployment openmetadata-dependencies-api-server \
  -n "$OM_NAMESPACE" >/dev/null 2>&1; do
  sleep 2
done
kubectl rollout status deployment/openmetadata-dependencies-api-server \
  --namespace "$OM_NAMESPACE" --timeout=600s || \
  echo "WARNING: Airflow api-server did not reach ready within 10 minutes (memory pressure?). Continuing -- OM server can still start."

# --- OIDC credentials Secret --------------------------------------
# Server values reference `oidc-secrets` via secretRef for the OIDC
# client id and secret. Re-applied on every run so a rotated client
# secret in .env propagates without a stale-secret error.
echo ""
echo "Creating/updating Secret oidc-secrets ..."
kubectl create secret generic oidc-secrets \
  --namespace "$OM_NAMESPACE" \
  --from-literal=openmetadata-oidc-client-id="$KEYCLOAK_CLIENT_ID" \
  --from-literal=openmetadata-oidc-client-secret="$KEYCLOAK_CLIENT_SECRET" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

# --- Server -------------------------------------------------------
echo ""
echo "Installing/upgrading $OM_RELEASE_SERVER ..."
helm upgrade --install "$OM_RELEASE_SERVER" \
  open-metadata/openmetadata \
  --version "$OM_CHART_VERSION" \
  --namespace "$OM_NAMESPACE" \
  --values "$PROJECT_DIR/local-k8s-values.yaml" \
  --set openmetadata.config.authentication.clientId="$KEYCLOAK_CLIENT_ID"

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
if kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/instance="$OM_RELEASE_SERVER" \
  --namespace "$OM_NAMESPACE" \
  --timeout=600s 2>/dev/null; then
  OM_READY=1
else
  OM_READY=0
fi

echo ""
kubectl get pods --namespace "$OM_NAMESPACE"
echo ""
echo "----------------------------------------------------------------"
if [ "$OM_READY" = "1" ]; then
  echo "OpenMetadata deployment complete -- all critical pods Ready."
else
  echo "OpenMetadata deployment finished, but the server pod did not"
  echo "reach Ready within 10 minutes. Check:"
  echo "  kubectl get pods -n $OM_NAMESPACE"
  echo "  kubectl logs -n $OM_NAMESPACE -l app.kubernetes.io/name=openmetadata --tail=50"
fi
echo ""
echo "Open https://${OM_DNS_NAME}/signin in a browser. Login is now"
echo "handled by Keycloak at ${KEYCLOAK_URL} (realm: ${KEYCLOAK_REALM:-solace-lab})."
echo "Sign in with the realm admin (admin / admin@solace.lab) for the"
echo "initial OM admin -- the email principal matches initialAdmins."
echo ""
echo "Ingestion bot JWT:"
echo "  Settings -> Bots -> ingestion-bot -> Token"
echo "Use this token as OM_INGESTION_BOT_TOKEN in your ingestion configs."
echo "----------------------------------------------------------------"
