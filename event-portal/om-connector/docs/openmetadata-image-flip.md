# Flipping OpenMetadata to the custom ingestion image

After `./scripts/build-and-push.sh` succeeds, two Helm values files
need to point at the new image so the workflow Airflow workers can
import `connector.event_portal_connector`.

## 1. Dependencies chart — Airflow workers

In `openmetadata-deployment/local-k8s-deps-values.yaml`, change:

```yaml
airflow:
  enabled: true
  airflow:
    image:
      repository: docker.getcollate.io/openmetadata/ingestion
      tag: 1.6.5
```

to:

```yaml
airflow:
  enabled: true
  airflow:
    image:
      repository: registry.solace.lab/openmetadata-ingestion-solace
      tag: 0.3.0
      pullPolicy: IfNotPresent
```

## 2. Apply

```bash
cd openmetadata-deployment
helm upgrade openmetadata-dependencies \
  open-metadata/openmetadata-dependencies \
  --namespace openmetadata-solace-lab \
  --values local-k8s-deps-values.yaml
```

The Airflow pods restart with the new image.

## 3. Verify

```bash
kubectl -n openmetadata-solace-lab \
  exec deploy/openmetadata-dependencies-web -- \
  python -c "from connector.event_portal_connector import SolaceEventPortalSource; print('OK')"
```

Output should be `OK`. If you see `ModuleNotFoundError: No module named
'connector'`, the new image is not actually in use yet — check pod
events with `kubectl describe pod ...` for `ImagePullBackOff` (probably
the lab cluster cannot reach `registry.solace.lab` or the pull secret
isn't wired up).

## 4. Rollback

```bash
# Revert local-k8s-deps-values.yaml to the previous image, then:
helm upgrade openmetadata-dependencies \
  open-metadata/openmetadata-dependencies \
  --namespace openmetadata-solace-lab \
  --values local-k8s-deps-values.yaml
```
