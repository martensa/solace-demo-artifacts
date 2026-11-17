#!/usr/bin/env bash
# G0-07: build the spike image and deploy gebitsim behind the lab ingress.
# Vendor descriptor sets are read from GEBIT_DESCRIPTOR_DIR (local path,
# never the repo) into the Secret gpos-g0-gebit-descriptors.
set -euo pipefail
cd "$(dirname "$0")"

NS=gpos-g0
DESC_DIR="${GEBIT_DESCRIPTOR_DIR:-$HOME/Downloads/Gebit}"
PURCHASE="$DESC_DIR/purchase-api-2.50.0.pb"
RECEIPT="$DESC_DIR/receipt-api-2.13.0.pb"

for f in "$PURCHASE" "$RECEIPT"; do
  [[ -r "$f" ]] || { echo "missing descriptor set: $f" >&2; exit 1; }
done

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  docker buildx build --load -t gpos-g0-grpc:spike \
    --build-context gebitsim=../../grpc-spike/gebitsim .
fi

kubectl apply -f k8s/00-namespace.yaml
# wait for the Kyverno clone of the pull secret and the trust bundle
for _ in $(seq 1 30); do
  kubectl get -n "$NS" secret/registry-pull-secret \
    configmap/solace-lab-ca-trust-bundle >/dev/null 2>&1 && break
  sleep 2
done

# server-side apply: no last-applied annotation (would double the size)
kubectl create secret generic gpos-g0-gebit-descriptors -n "$NS" \
  --from-file=purchase-api-2.50.0.pb="$PURCHASE" \
  --from-file=receipt-api-2.13.0.pb="$RECEIPT" \
  --dry-run=client -o yaml \
  | kubectl apply --server-side --field-manager=gpos-g0-07 -f -

kubectl apply -f k8s/20-certificate.yaml
kubectl apply -f k8s/10-grpc.yaml -f k8s/40-upload.yaml
kubectl wait -n "$NS" certificate/gpos-g0-grpc --for=condition=Ready \
  --timeout=120s
kubectl apply -f k8s/30-ingress-grpc.yaml
kubectl rollout status -n "$NS" deploy/gpos-g0-grpc --timeout=120s
kubectl rollout status -n "$NS" deploy/gpos-g0-upload --timeout=120s
kubectl get -n "$NS" deploy,svc,ingress,certificate
