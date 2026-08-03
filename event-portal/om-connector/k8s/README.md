# Bridge — Lab Kubernetes manifests

Minimal raw manifests for running the webhook bridge in the same
`openmetadata-solace-lab` namespace as the OM server. **Demo-grade**:
single replica, in-memory dedupe, no Prometheus / OTel wiring yet.
Production hardening lives in Phase 2 (Helm chart, Redis dedupe,
ServiceMonitor, HPA, NetworkPolicy).

## Files

| File              | What it provides                                    |
| ----------------- | --------------------------------------------------- |
| `00-secret.yaml`  | EP token, webhook signing secret, OM JWT — populate before apply |
| `01-configmap.yaml` | Non-secret env (OM host, EP base URL, mode)        |
| `02-deployment.yaml` | Single-replica Deployment of the bridge image    |
| `03-service.yaml` | ClusterIP service on port 8080                     |
| `04-ingress.yaml` | nginx Ingress on `bridge.solace.lab` + cert-manager |

## Pre-flight

1. The OM-side bootstrap has already run (Classification + Custom
   Properties + PipelineService exist).
2. The lab has the `registry-pull-secret` injected via the Kyverno
   policy from `solace-lab-infrastructure` (same as agent-mesh).
3. The bridge image is in the lab registry — build via:

   ```bash
   docker build -f Dockerfile.bridge -t registry.solace.lab/om-eventportal-bridge:0.3.0 .
   docker push registry.solace.lab/om-eventportal-bridge:0.3.0
   ```

4. `bridge.solace.lab` resolves to the ingress (same CoreDNS NodeHosts
   pattern as SAM and the OM deployment).

## Apply

```bash
# 1. Populate the secret file (do NOT commit the populated version)
cp 00-secret.yaml /tmp/bridge-secret.yaml
$EDITOR /tmp/bridge-secret.yaml   # fill in EP_API_TOKEN, EP_WEBHOOK_SECRET, OM_JWT_TOKEN

# 2. Apply in order
kubectl apply -f /tmp/bridge-secret.yaml
kubectl apply -f 01-configmap.yaml
kubectl apply -f 02-deployment.yaml
kubectl apply -f 03-service.yaml
kubectl apply -f 04-ingress.yaml

# 3. Wait for ready
kubectl -n openmetadata-solace-lab \
  wait --for=condition=ready pod -l app=solace-eventportal-bridge --timeout=120s

# 4. Smoke
curl -fsSL https://bridge.solace.lab/healthz
#   -> {"status":"ok"}

# 5. Register the webhook with EP (idempotent)
kubectl -n openmetadata-solace-lab \
  exec deploy/solace-eventportal-bridge -- \
  om-eventportal-bridge --register-webhook \
    https://bridge.solace.lab/webhook/event-portal
```

## Teardown

```bash
kubectl -n openmetadata-solace-lab delete \
  ingress/solace-eventportal-bridge \
  service/solace-eventportal-bridge \
  deployment/solace-eventportal-bridge \
  configmap/solace-eventportal-bridge \
  secret/solace-eventportal-bridge
```

## Demo Act 5 (resilience) helpers

```bash
# stop
kubectl -n openmetadata-solace-lab scale deploy solace-eventportal-bridge --replicas=0

# start
kubectl -n openmetadata-solace-lab scale deploy solace-eventportal-bridge --replicas=1
kubectl -n openmetadata-solace-lab \
  wait --for=condition=ready pod -l app=solace-eventportal-bridge --timeout=60s

# replay audit since watermark
kubectl -n openmetadata-solace-lab \
  exec deploy/solace-eventportal-bridge -- \
  om-eventportal-bridge --reconcile
```
