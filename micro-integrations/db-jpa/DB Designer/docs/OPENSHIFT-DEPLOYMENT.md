# DB Designer on OpenShift -- Deployment Runbook

This runbook deploys the **DB Designer** (Connector Control Center)
component of the Solace `db-jpa` Micro-Integration to a Red Hat
OpenShift cluster. It targets a Bosch OpenShift platform engineer and
is a precise, step-by-step procedure: build and push the hardened
images, configure the OpenShift Helm overlay, install the chart, and
verify the result.

The Helm chart lives at
`micro-integrations/db-jpa/DB Designer/charts/db-designer`. All paths
below are relative to the `DB Designer` directory unless stated
otherwise. Directory names contain spaces, so quote them in the shell.

## What gets deployed

The component is three cooperating workloads in a single Helm release:

| Workload | Image | Container port | Purpose |
| --- | --- | --- | --- |
| `services` (backend) | `connector_designer_services` | `6002` | Node.js backend / meta-api |
| `ui` (frontend) | `connector_designer_ui` | `6003` | React Connector Control Center |
| Postgres (metadata) | external / operator-managed | `5432` | Designer metadata database |

Key deployment facts for OpenShift:

- The React UI calls the backend **from the browser**. Both the UI
  host and the API host must therefore be browser-resolvable. The
  chart creates two separate Routes: one for `route.uiHost` and one
  for `route.apiHost`. A single host is not sufficient.
- On OpenShift, Postgres is **external / operator-managed**
  (`postgres.embedded=false`). The bundled Postgres StatefulSet is a
  local-lab convenience only; do not use it here.
- The workload runs on the **hardened images** (tag
  `2.0.2-hardened`). These are non-root and support OpenShift's
  arbitrary-UID model, so they run under the **default `restricted-v2`
  SCC**. No cluster-admin and no custom SCC are required
  (`openshift.scc.create=false`).
- The backend is single-replica with a `Recreate` strategy. It keeps
  produced connector packages on an RWO PVC (`binary-downloads`);
  logs, tmp and entity folders use `emptyDir`.

## Residual risks (read before production sign-off)

The hardened overlay fixes only the root / arbitrary-UID problem. The
following remain **Solace deliverables ("Track 1")** and are not
resolved by this chart:

- The vendor images are **amd64-only** (single-arch) and run
  **Node 16.20.2**, which reached end-of-life in September 2023. The
  overlay does not change the Node runtime or the CVE surface.
- The vendor images are opaque (no Dockerfile / source is provided).
- The backend exposes **no `/health` endpoint** (a request to
  `/health` returns 404); the chart uses a `tcpSocket` probe instead.
- Some connector config templates under `artifacts/` carry demo
  external IPs and passwords that must be sanitized / parameterized
  for Bosch before use.

For a full Bosch production sign-off, Solace must ship
current-Node-LTS, multi-arch, security-scanned, registry-published
images. See `docs/SECURITY.md` and `docs/BOSCH-HANDOVER.md`.

Native amd64 on OpenShift avoids the emulation instability seen on the
single-node lab laptop, but does not address the EOL-Node / single-arch
items above.

## 1. Prerequisites

Confirm all of the following before starting.

### CLIs and access

- `oc` (OpenShift CLI), logged in to the target cluster:
  `oc whoami` returns your user.
- `helm` v3 (`helm version`).
- `docker` (or a compatible builder) on an **amd64** host or CI
  runner, to build and push the hardened images. The vendor base
  images are amd64-only; do not build them under emulation for
  production.
- The vendor image tarballs `connector_designer_services.tar` and
  `connector_designer_ui.tar` (obtained from Solace), or the vendor
  base images already present in your builder's local Docker.

### Cluster resources

- An OpenShift **project / namespace** you can deploy into
  (`oc new-project <project>` or an existing one). This runbook uses
  `db-designer` as the example namespace and release name.
- An **image registry reachable by the cluster**. The OpenShift
  internal registry
  (`image-registry.openshift-image-registry.svc:5000/<project>/...`)
  or a Bosch/Harbor registry both work. You need push access from the
  build host and pull access from the cluster.
- An **image pull secret** in the target namespace if the registry is
  not the cluster-internal one. Reference it by name via
  `imagePullSecrets` (see step 3).
- An **external Postgres** database (or a Postgres operator such as
  CloudNativePG / Crunchy) reachable from the namespace, with a
  database, user and password provisioned. The chart connects using
  `postgres.external.host` / `postgres.external.port`.
- An RWO **StorageClass** for the backend's `binary-downloads` PVC
  (5Gi by default on this overlay).
- An **application / Route domain** (`*.apps.<cluster>.<domain>`), or
  two explicit custom hostnames plus the corresponding DNS records.
- **Cluster CA trust** if the Designer's in-pod Java processes (entity
  generator / meta-api) must reach TLS endpoints signed by an internal
  CA (see step 3, Java truststore, and the CA-trust note in step 7).

Because the hardened images satisfy `restricted-v2`, you do **not**
need cluster-admin to install this chart.

## 2. Build and push the hardened images

The hardened images are thin overlays built FROM the Solace vendor
images. They add `USER 1001`, make the runtime-writable directories
group-owned by GID 0 and group-writable, and set `HOME=/tmp` so any
arbitrary UID assigned by OpenShift can run and write. Verified: they
run as an arbitrary UID (for example `26999:0`) with writable runtime
dirs and satisfy the default `restricted-v2` SCC.

Build and push with `hardened-images/build.sh <REGISTRY> [TAG]`. The
default tag is `2.0.2-hardened`.

```bash
cd "micro-integrations/db-jpa/DB Designer"

# Ensure the vendor base images are present on the amd64 build host:
docker load -i connector_designer_services.tar
docker load -i connector_designer_ui.tar

# Build + push both hardened images to your registry:
./hardened-images/build.sh <REGISTRY> 2.0.2-hardened
```

Replace `<REGISTRY>` with the registry the cluster pulls from, for
example `image-registry.apps.<cluster>.<domain>/db-designer` or your
Bosch/Harbor path. The script builds `linux/amd64` by default
(override with `PLATFORM=`), tags each image
`<REGISTRY>/connector_designer_services:2.0.2-hardened` and
`<REGISTRY>/connector_designer_ui:2.0.2-hardened`, and pushes them.

If your base images are named differently, override with the
`SERVICES_BASE` and `UI_BASE` environment variables.

Verify both tags exist in the registry before continuing.

## 3. Configure `values-openshift.yaml`

Edit `charts/db-designer/values-openshift.yaml` (or keep it clean and
supply the values via `--set` / an extra `-f` file). The overlay
already sets `platform: openshift`, `ingress.enabled: false`,
`route.enabled: true`, `postgres.embedded: false`, and
`openshift.scc.create: false`. Fill in the target-specific keys:

### Image repository and tag

```yaml
image:
  services:
    repository: <REGISTRY>/connector_designer_services
    tag: "2.0.2-hardened"
    pullPolicy: Always
  ui:
    repository: <REGISTRY>/connector_designer_ui
    tag: "2.0.2-hardened"
    pullPolicy: Always
```

### Image pull secret

Set to the pull secret that exists in the target namespace (Kyverno
auto-injection is a lab-only convenience and is not assumed here):

```yaml
imagePullSecrets:
  - name: registry-pull-secret
```

### Routes (browser-resolvable UI and API hosts)

Both hosts are **required** on OpenShift -- the chart's helpers will
fail the render otherwise, because the browser must reach both.

```yaml
route:
  enabled: true
  uiHost: db-designer.apps.<cluster>.<domain>
  apiHost: db-designer-api.apps.<cluster>.<domain>
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
```

The UI Route targets the `db-designer-ui` Service (port `6003`); the
API Route targets the `db-designer-services` Service (port `6002`).
The chart injects `https://<apiHost>` into the browser runtime config
(`REACT_APP_API_SERVICES_URL`), so `apiHost` must resolve and serve a
valid TLS certificate from the browser.

### External Postgres

```yaml
postgres:
  embedded: false
  external:
    host: <postgres-host>     # REQUIRED when embedded=false
    port: 5432
```

The rendered backend `.env` uses `postgres.user` (default `postgres`),
`postgres.database` (default `CONNECTOR_DESIGNER_TEST`),
`postgres.schema` (default `CM_SCHEMA`) and `postgres.type` (default
`postgres`). Adjust these under `postgres:` to match the provisioned
database; the password is a secret (step 4). Ensure the target
database and schema exist, or that the DB user may create the schema.

### Storage class

```yaml
servicesApp:
  persistence:
    enabled: true
    size: 5Gi
    storageClass: <rwo-storage-class>
```

### Optional: internal-CA trust for in-pod Java

If the entity generator / meta-api must trust an internal CA over TLS,
provide the CA bundle as a ConfigMap in the namespace and enable both:

```yaml
labCaTrust:
  enabled: true
  configMapName: <ca-bundle-configmap>   # must contain key ca.crt
servicesApp:
  javaTruststore:
    enabled: true
```

This runs an init container that imports `ca.crt` into a Java
truststore and sets `JAVA_TOOL_OPTIONS` on the backend. `SSL_CERT_FILE`
alone does not affect the JVM.

## 4. Create the `.env` for secret overrides

Sensitive values are injected via `helm --set` from a gitignored
`.env`, never committed. Copy the template and set real values:

```bash
cp .env.example .env
```

`.env` keys (all optional; each has a demo default baked into the
chart, so leaving one unset keeps the demo value -- override every
sensitive one for Bosch):

| `.env` variable | Chart value key | Purpose |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | `secret.postgresPassword` | External Postgres password |
| `SOLACE_CLIENT_PASSWORD` | `secret.solaceClientPassword` | Broker client password |
| `SOLACE_MGMT_PASSWORD` | `secret.solaceMgmtPassword` | Broker SEMP password |
| `SOLACE_API_TOKEN` | `secret.solaceApiToken` | Solace Cloud API token |
| `SECRET_APP_KEY` | `secret.appSecretKey` | Backend session secret |
| `SECRET_REFRESH_KEY` | `secret.appRefreshTokenKey` | Backend refresh-token key |
| `PASSWORD_ENCRYPTION_KEY` | `secret.passwordEncryptionKey` | UI/backend field encryption |
| `ADMIN_USER_PASSWORD` | `secret.adminUserPassword` | Designer admin login password |

The chart assembles the backend `.env` file (mounted at
`/app/dist/bin/.env`) from these plus the non-secret `config.*` values.
Non-secret broker endpoints live under `config.solace.*` in
`values.yaml` (host, VPN, users, REST/SEMP ports); override them per
deployment via your overlay or `--set`.

The `scripts/start.sh` helper targets the local Rancher lab (image
tarball loading, CoreDNS, `/etc/hosts`, the Rancher overlay) and is
**not** used on OpenShift. On OpenShift, run `helm` directly as in
step 5, sourcing the same `.env` variables into `--set` flags.

## 5. Install the chart

Create the project, ensure the pull secret and Postgres exist, then
install. Example, sourcing `.env` and passing secrets via `--set`:

```bash
cd "micro-integrations/db-jpa/DB Designer"
export NAMESPACE=db-designer
export RELEASE=db-designer

oc new-project "$NAMESPACE" 2>/dev/null || oc project "$NAMESPACE"

set -a; . ./.env; set +a

helm upgrade --install "$RELEASE" charts/db-designer \
  --namespace "$NAMESPACE" \
  -f charts/db-designer/values-openshift.yaml \
  --set secret.postgresPassword="$POSTGRES_PASSWORD" \
  --set secret.solaceClientPassword="$SOLACE_CLIENT_PASSWORD" \
  --set secret.solaceMgmtPassword="$SOLACE_MGMT_PASSWORD" \
  --set secret.appSecretKey="$SECRET_APP_KEY" \
  --set secret.appRefreshTokenKey="$SECRET_REFRESH_KEY" \
  --set secret.passwordEncryptionKey="$PASSWORD_ENCRYPTION_KEY" \
  --set secret.adminUserPassword="$ADMIN_USER_PASSWORD" \
  --set secret.solaceApiToken="$SOLACE_API_TOKEN"
```

If a value in `route.uiHost`, `route.apiHost`,
`postgres.external.host`, `image.*.repository`, `imagePullSecrets` or
`servicesApp.persistence.storageClass` is not yet in
`values-openshift.yaml`, add a matching `--set` for it.

The install creates (release `db-designer`): Deployments
`db-designer-services` and `db-designer-ui`, Services
`db-designer-services` / `db-designer-ui`, Routes `db-designer-ui` and
`db-designer-api`, the `db-designer-env` Secret, the
`db-designer-ui-env` ConfigMap, the `db-designer-binary-downloads`
PVC, a NetworkPolicy, and the `db-designer` ServiceAccount. No SCC and
no Postgres StatefulSet are created on this overlay.

## 6. Verify the deployment

### Pods and rollout

```bash
oc -n db-designer rollout status deploy/db-designer-services
oc -n db-designer rollout status deploy/db-designer-ui
oc -n db-designer get pods -l app.kubernetes.io/instance=db-designer
```

Expect the `services` and `ui` pods to reach `1/1 Running`. (There is
no Postgres pod on OpenShift -- it is external.) Confirm the pods run
under a non-root, project-assigned UID:

```bash
oc -n db-designer get pod -l app.kubernetes.io/component=services \
  -o jsonpath='{.items[0].spec.containers[0].securityContext}{"\n"}'
```

You should see `allowPrivilegeEscalation: false`,
`runAsNonRoot: true`, and `capabilities.drop: [ALL]`.

### Routes

```bash
oc -n db-designer get route
```

Both `db-designer-ui` and `db-designer-api` should show their host and
`edge` termination.

### API host reachable from the browser side

The backend has no `/health` path, so a `curl` to `/health` returns a
404 from the backend -- that is expected and still proves the API host
resolves, terminates TLS, and reaches the backend:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  https://db-designer-api.apps.<cluster>.<domain>/health
```

A `404` (backend answered) or another backend HTTP status confirms the
API Route path end to end. A connection/TLS error means DNS, the
Route, or the certificate is wrong (see Troubleshooting).

### UI in the browser

Open `https://db-designer.apps.<cluster>.<domain>` in a browser. The
page title is "Connector Control Center". Log in with the admin user
(demo credentials `admin` / `admin` unless you overrode
`ADMIN_USER_PASSWORD`). Confirm in the browser dev tools that the UI's
XHR calls target `https://<apiHost>` and succeed -- this is the
browser-to-API-host path that the two-Route design exists to serve.

## 7. DNS, Route and certificate notes

- On the default `*.apps.<cluster>.<domain>` wildcard, both Route
  hosts resolve automatically and the OpenShift default ingress
  certificate is served. No extra DNS or certs are needed.
- For **custom** hostnames outside the wildcard, create DNS records
  for both `route.uiHost` and `route.apiHost` pointing at the cluster
  ingress, and supply a certificate for each Route (edit the Route TLS
  block or manage certs via cert-manager / the ingress operator).
- Routes are **edge-terminated** with
  `insecureEdgeTerminationPolicy: Redirect`, so HTTP is redirected to
  HTTPS. The backend Service is plain HTTP inside the cluster.
- Because the UI calls the API from the browser, the browser must
  trust the API host's certificate. A self-signed or internal-CA cert
  on `apiHost` that the browser does not trust will make the UI's API
  calls fail even though the pods are healthy. Use a
  browser-trusted certificate on `apiHost`.
- The `NetworkPolicy` allows ingress from the OpenShift router
  namespace and intra-release traffic, DNS egress, and general egress
  (broker, target databases, meta-api introspection). If your cluster
  labels the router namespace differently, set
  `networkPolicy.ingressNamespace` accordingly, or disable it with
  `networkPolicy.enabled=false` if a cluster-wide policy already
  governs the namespace.

## 8. Troubleshooting

### Image pull failures (`ImagePullBackOff` / `ErrImagePull`)

- Confirm `image.services.repository` / `image.ui.repository` point at
  the pushed hardened images and the tag `2.0.2-hardened` exists in the
  registry.
- Confirm `imagePullSecrets` names a secret that exists in the
  `db-designer` namespace and has pull rights:
  `oc -n db-designer get secret`. Link it to the ServiceAccount or
  keep it referenced via the values key.
- `oc -n db-designer describe pod <pod>` shows the exact registry
  path and auth error.

### Arbitrary-UID / SCC errors

- If a pod fails admission with a `runAsNonRoot` / UID error, you are
  almost certainly on the **un-hardened** vendor images (they run as
  root). Rebuild with `hardened-images/build.sh` and point the image
  repositories at the `2.0.2-hardened` tags.
- Do **not** set `openshift.scc.create=true` for the hardened images;
  they need no custom SCC. That flag exists only for the un-hardened
  images and requires cluster-admin to install.
- Confirm the pod's assigned SCC:
  `oc -n db-designer get pod <pod> -o \`
  `jsonpath='{.metadata.annotations.openshift\.io/scc}'` should read
  `restricted-v2`.

### External database connectivity

- The backend `.env` is built from `postgres.external.host`,
  `postgres.external.port`, `postgres.user`, `postgres.database` and
  the injected `secret.postgresPassword`. A blank
  `postgres.external.host` fails the Helm render with a `required`
  error -- set it.
- From a backend pod, test reachability:
  `oc -n db-designer exec deploy/db-designer-services -- \`
  `sh -c 'nc -zv <postgres-host> 5432'`.
- Verify the database, user and schema (`CM_SCHEMA` by default) exist
  and the user may use them. NetworkPolicy egress is open, so a
  failure is DNS, credentials, the database firewall, or a missing
  schema -- not the policy.

### Browser cannot reach the API host

- Symptom: the UI loads but every action fails; browser dev tools show
  failed XHR to `https://<apiHost>`.
- Check the API Route resolves and answers:
  `curl -v https://<apiHost>/health` (a 404 is fine; a TLS or
  connection error is not).
- Confirm `route.apiHost` DNS exists and its certificate is
  browser-trusted. An internal-CA cert on `apiHost` that the browser
  distrusts is the most common cause.
- Confirm the injected browser config is correct:
  `oc -n db-designer get configmap db-designer-ui-env -o yaml`
  should show `REACT_APP_API_SERVICES_URL='https://<apiHost>'`.

### Backend probes flapping

- The backend has no `/health`; the chart uses `tcpSocket` probes with
  generous initial delays. If the `services` pod restarts on
  liveness, check `oc -n db-designer logs deploy/db-designer-services`
  for a startup error (bad DB credentials, unreachable broker, missing
  schema) rather than assuming a probe misconfiguration.

## 9. Uninstall

```bash
helm uninstall db-designer --namespace db-designer
```

This removes the release objects. The `db-designer-binary-downloads`
PVC and any Route certificates you created out of band may persist;
delete the namespace to remove the PVC. The external Postgres is not
managed by the chart and is left untouched.

## Production hardening checklist

Before a Bosch production sign-off, confirm each item and cross-check
the detailed docs:

- [ ] Running the **hardened images** (`2.0.2-hardened`), non-root,
      under `restricted-v2`; no custom SCC; not cluster-admin.
- [ ] All secrets overridden from a real `.env` via `--set`; **no**
      demo credentials (`admin`/`admin`, `postgres`, `coeadmin`,
      `TEST`) remaining. See `docs/SECURITY.md`.
- [ ] External / operator-managed Postgres, with least-privilege
      credentials and the required schema.
- [ ] `route.uiHost` and `route.apiHost` resolve and serve
      browser-trusted certificates.
- [ ] Connector config templates under `artifacts/` sanitized --
      no demo external IPs or passwords.
- [ ] **Track 1 items acknowledged with Solace**: current-Node-LTS,
      multi-arch, security-scanned, registry-published images; source
      transparency; a real backend health endpoint. See
      `docs/SECURITY.md` and `docs/BOSCH-HANDOVER.md`.

For the full security posture (securityContext, NetworkPolicy, secret
handling, residual CVE surface) see `docs/SECURITY.md`. For the
overall handover scope, ownership split, and open Solace deliverables
see `docs/BOSCH-HANDOVER.md`.
