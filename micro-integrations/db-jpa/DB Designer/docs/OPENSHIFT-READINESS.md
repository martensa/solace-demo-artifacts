# DB Designer -- OpenShift Readiness Assessment

## Purpose and scope

This is a **simulated** readiness assessment for deploying the DB Designer
Helm chart (`values-openshift.yaml`, hardened images) on Red Hat OpenShift
under the default `restricted-v2` Security Context Constraint. It targets
the parts where OpenShift differs from a plain Kubernetes/k3s lab: the
`restricted-v2` SCC (non-root, arbitrary UID, dropped privileges), the
`Route` and `SecurityContextConstraints` objects, and the image behaviour
under an OpenShift-assigned UID.

**It is NOT a production sign-off.** No real OpenShift cluster was used --
the checks run against a PodSecurity `restricted` namespace on k3s (the
Kubernetes-native equivalent of `restricted-v2` at the pod-spec level) plus
image-level runtime tests. A binding release still requires the cluster-side
items in [Residual conditions](#residual-conditions-for-production-sign-off).

Verdict: **CONDITIONAL GO** -- the chart and hardened images are
OpenShift-`restricted-v2`-ready by construction and pass every check that
can be evaluated off-cluster. Remaining gates are environment- and
vendor-owned, not chart defects.

## Environment simulated

- Chart: `charts/db-designer` with `values-openshift.yaml`, hardened images
  (`connector-designer-services:2.0.2-hardened`,
  `connector-designer-ui:2.0.2-hardened`), external Postgres, Routes, no
  custom SCC.
- k3s v1.34 with a namespace labelled
  `pod-security.kubernetes.io/enforce=restricted` (+ warn/audit).
- Image runtime tests via `docker run --user 1000680000:0` (a
  representative OpenShift project-range UID with GID 0).

## Test results

<!-- markdownlint-disable MD013 -->

| # | Check | Method | Result |
| --- | --- | --- | --- |
| 1 | Chart renders + lints for OpenShift | `helm lint` + `helm template` (values-openshift.yaml) | PASS -- 2 Deployments, 2 Routes, NetworkPolicy, Secret, 3 ConfigMaps, 3 PVCs, ServiceAccount; **0 SCC** (hardened images need none), external DB |
| 2 | Workloads pass `restricted` admission | `kubectl apply --dry-run=server` of all 13 workload objects in a PodSecurity `restricted` namespace | PASS -- all objects admitted, **zero** PodSecurity warnings |
| 3 | Pods pass `restricted` ENFORCE at an arbitrary UID | Pod templates extracted, forced to `runAsUser: 1000680000, runAsGroup: 0, fsGroup: 1000680000`, `--dry-run=server` under `enforce=restricted` | PASS -- both app pods admitted |
| 4 | Hardened images RUN as an arbitrary UID | `docker run --user 1000680000:0` on both images | PASS -- `id=1000680000:0`, Node runs, `HOME=/tmp`, writes to runtime dirs OK, UI serves its build |
| 5 | Container securityContext posture | inspection of the rendered pod specs | PASS -- `runAsNonRoot: true`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`, `seccompProfile: RuntimeDefault` |
| 6 | Route objects | structural validation of `route.openshift.io/v1` render | PASS -- UI + API Routes, correct backend Services, `targetPort: http`, edge TLS with redirect |
| 7 | SCC fallback object (un-hardened path) | structural validation with `openshift.scc.create=true` | PASS -- drops ALL caps, no privilege escalation, `seccompProfiles: runtime/default`, bound to the release ServiceAccount (needs cluster-admin; NOT used with hardened images) |

<!-- markdownlint-enable MD013 -->

## What this establishes

- The workload **admits and runs under `restricted-v2`** without a custom
  SCC and without cluster-admin: the hardened images are non-root and
  tolerate an OpenShift-assigned arbitrary UID (GID 0), and every pod-level
  control the `restricted` profile mandates is set.
- The embedded Postgres path is correctly **defaulted off** for OpenShift:
  the official `postgres` image pins UID 999, which `restricted-v2` rejects
  (UID must come from the project range). The overlay targets an external /
  operator-managed database instead.
- The OpenShift-specific objects (`Route`, optional `SCC`) render correctly.

## Residual conditions for production sign-off

These require the actual target cluster or the vendor and are out of scope
for an off-cluster simulation:

- **Real `restricted-v2` admission on the target cluster.** PodSecurity
  `restricted` is the pod-spec-level equivalent; the OpenShift SCC also
  assigns the UID from the project's `uid-range`. Our app pods do not pin a
  UID, so they accept the assigned range (expected pass) -- confirm on the
  cluster. Owner: **customer platform team**.
- **Image supply chain.** Push the bundle images to the customer registry
  (`scripts/load-and-push.sh`), wire `imagePullSecrets`, and run the
  customer's CVE/compliance scanner. The scanner WILL flag the vendor base
  (Node 16 EOL). Owner: **customer + Solace (Track 1)**.
- **External database.** Provision the Postgres (operator/managed) and
  confirm connectivity + credentials. Owner: **customer DB ops**.
- **Route DNS + TLS.** Set `route.uiHost` / `route.apiHost` to the cluster
  app domain and confirm the Router serves browser-trusted certificates
  (the UI calls the API from the browser, so BOTH must resolve). Owner:
  **customer platform team**.
- **Full application smoke on OpenShift.** The images run as an arbitrary
  UID (proven) and the full app ran 1/1 on k3s; a final end-to-end smoke on
  the target cluster closes the loop. Owner: **customer + us**.

## How to reproduce

```bash
cd "micro-integrations/db-jpa/DB Designer/charts/db-designer"
# 1. render + lint
helm lint . -f values-openshift.yaml
helm template db-designer . -f values-openshift.yaml \
  --set route.uiHost=... --set route.apiHost=... \
  --set postgres.external.host=... > /tmp/ocp.yaml
# 2. restricted-namespace admission
kubectl create ns ocp-sim
kubectl label ns ocp-sim pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/warn=restricted
# strip the Route + SCC (OpenShift CRDs) then:
kubectl -n ocp-sim apply --dry-run=server -f /tmp/ocp-workloads.yaml
# 3. image UID test
docker run --rm --user 1000680000:0 --entrypoint sh \
  connector-designer-services:2.0.2-hardened -c 'id; node --version'
```

## Related documents

- `docs/OPENSHIFT-DEPLOYMENT.md` -- deployment runbook.
- `docs/SECURITY.md` -- security posture and residual-risk register.
- `docs/CUSTOMER-HANDOVER.md` -- overall handover scope.
