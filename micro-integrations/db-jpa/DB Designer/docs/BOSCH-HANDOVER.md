# DB Designer -- Bosch Handover

## Executive summary

This package hardens and productionizes the **DB Designer** (Connector
Control Center) component of the Solace `db-jpa` Micro-Integration for
deployment on Bosch OpenShift. It wraps the Solace-provided container
images in a single Helm chart that adds non-root execution, TLS, network
isolation, secret externalization, and support for an external
(operator-managed) Postgres. The chart has been verified end to end on a
local Kubernetes lab and is structured to deploy on OpenShift under the
**default** restricted-v2 Security Context Constraint -- no cluster-admin
and no custom SCC required. What remains outside our control is a short,
explicit list of image-level deliverables that only Solace can ship
("Track 1"), summarized below and detailed in `SECURITY.md`.

## What this is

The DB Designer is a low-code **Connector Control Center**: a web
application in which an integrator models a source or sink data flow,
introspects a relational database schema, drives generation of the JPA
entity code, and produces a downloadable, runnable **connector package**.
That package (connector jar plus config plus generated `entity.jar` plus a
launcher) is exactly what the runtime **DB Connector** executes against a
Solace PubSub+ broker and a database. In short, the Designer is the
build-and-package front end of the `db-jpa` pipeline; it is not itself on
the runtime data path.

## What is delivered in this package

<!-- markdownlint-disable MD013 -->

| Deliverable | Path | Purpose |
| --- | --- | --- |
| Helm chart | `charts/db-designer/` | Deploys the 3 workloads plus Ingress/Route, NetworkPolicy, Secret, PVC, ServiceAccount |
| Base values | `charts/db-designer/values.yaml` | Non-sensitive, safe-to-commit defaults (ports, resources, hosts) |
| Rancher overlay | `charts/db-designer/values-rancher.yaml` | Local lab: nginx Ingress, cert-manager, embedded Postgres |
| OpenShift overlay | `charts/db-designer/values-openshift.yaml` | Bosch: Routes, hardened images, external Postgres, no SCC |
| Hardened image overlays | `hardened-images/Dockerfile.services`, `Dockerfile.ui` | Add non-root + arbitrary-UID support on top of vendor images |
| Image build script | `hardened-images/build.sh` | Builds and pushes the `2.0.2-hardened` images |
| Deploy scripts | `scripts/start.sh`, `scripts/stop.sh` | One-command lab install and teardown |
| Secret template | `.env.example` | Deploy-time secret overrides injected via `helm --set` |
| Security posture | `docs/SECURITY.md` | Controls, image supply chain, residual-risk register |
| OpenShift runbook | `docs/OPENSHIFT-DEPLOYMENT.md` | Step-by-step OpenShift deployment procedure |

<!-- markdownlint-enable MD013 -->

## Architecture overview

The Designer sits between the entity-generation CLI and the runtime
connector. Its own deployment is three cooperating workloads.

```text
   DB CLI  --entity.jar-->  DB Designer  --connector package-->  DB Connector
                            (this package)

   DB Designer (Helm release)
   +-----------------------------------------------------------+
   |                                                           |
   |   browser                                                 |
   |     |  HTTPS (uiHost)          HTTPS (apiHost)            |
   |     v                              |                       |
   |  +-----------+                     v                       |
   |  |    UI     |               +-----------+                 |
   |  | React SPA |               | services  |                 |
   |  |  :6003    |               | Node API  |                 |
   |  +-----------+               |  :6002    |                 |
   |                              +-----+-----+                 |
   |    NOTE: the UI calls the API      | JDBC :5432            |
   |    FROM THE BROWSER, so BOTH       v                       |
   |    hosts are browser-resolvable +-----------+              |
   |    (separate Ingress / Routes). | Postgres  |              |
   |                                 | metadata  |              |
   |                                 |  :5432    |              |
   |                                 +-----------+              |
   +-----------------------------------------------------------+
```

Ports: UI `6003`, backend API `6002`, Postgres metadata DB `5432`. The
backend is a single replica (`Recreate` strategy) because it keeps local
state; produced connector packages persist on an RWO PVC, while logs, tmp,
and entity folders use `emptyDir`.

## Two deployment modes

Both modes are the same chart with a different values overlay.

- **Local Rancher lab** (`values-rancher.yaml`) -- nginx Ingress,
  cert-manager issuer `solace-lab-ca-issuer`, Kyverno-injected CA trust
  and registry pull secret, and an embedded Postgres StatefulSet. Deploy
  with `scripts/start.sh`.
- **Bosch OpenShift** (`values-openshift.yaml`) -- OpenShift Routes
  (edge-terminated TLS), the hardened `2.0.2-hardened` images, and an
  external / operator-managed Postgres. Runs under the default
  restricted-v2 SCC; see `docs/OPENSHIFT-DEPLOYMENT.md`.

## Enterprise readiness (production-ready now)

The following controls are implemented and verified in this package:

- **Non-root under the default SCC.** The hardened overlay images
  (`hardened-images/Dockerfile.*`) add `USER 1001` plus OpenShift
  arbitrary-UID support (runtime dirs group-owned by GID 0 and
  group-writable, `HOME=/tmp`). Verified running as an arbitrary UID
  (`26999:0`) with writable runtime dirs, so they satisfy OpenShift's
  **default restricted-v2 SCC** -- no cluster-admin and no custom SCC.
- **Container hardening on every app pod.**
  `allowPrivilegeEscalation=false`, all capabilities dropped,
  `seccompProfile: RuntimeDefault`, `runAsNonRoot=true`. The root
  filesystem is not read-only because the app writes to mounted volumes.
- **TLS everywhere the UI is reached.** cert-manager-issued certificates
  in the lab; edge-terminated Routes on OpenShift.
- **Network isolation.** A NetworkPolicy admits ingress only from the
  router/ingress namespace and from intra-release pods; egress is limited
  to DNS plus the broker and database traffic the Designer needs.
- **Secret externalization.** The chart assembles the backend
  `/app/dist/bin/.env` from values; sensitive values are injected via
  `helm --set` from a gitignored `.env` (see `.env.example`). Only demo
  credentials are committed, and image tarballs, generated packages, and
  logs are gitignored.
- **External database.** On OpenShift the chart targets an external /
  operator-managed Postgres, keeping stateful data off the app pods and
  under Bosch database operations.

## What Solace must still deliver (Track 1)

The hardened overlay fixes root and arbitrary-UID execution, but it does
**not** modify the vendor application or its base runtime. For a full
Bosch production sign-off, Solace must ship:

- **Current-Node, multi-arch, scanned images.** The vendor images are
  amd64-only and run Node `16.20.2` (EOL September 2023). Solace must
  provide current-Node-LTS, multi-architecture, security-scanned, and
  registry-published images.
- **Image transparency.** The vendor images are opaque (no Dockerfile or
  source provided); Solace must supply the build source / Dockerfiles for
  supply-chain review.
- **A real health endpoint.** The backend exposes no `/health` path, so
  the chart falls back to a `tcpSocket` probe. A proper health/readiness
  endpoint is needed for robust OpenShift probes.
- **Sanitized config templates.** Some connector config templates carry
  demo external IPs and passwords that must be sanitized and parameterized
  before Bosch use.

The full register, including severities, is in `docs/SECURITY.md`.

## Known limitations

- **Single-arch runtime.** The images run natively only on amd64; there is
  no arm64 build (relevant for Apple Silicon laptops and arm nodes).
- **EOL Node base.** Node `16.20.2` carries an unpatched CVE surface that
  the overlay cannot fix; it is a base-image change owned by Solace.
- **No `/health` endpoint.** Probes are TCP-socket based (see above).
- **Single-replica backend.** The backend keeps local state, so it runs as
  one replica with a `Recreate` rollout strategy; it is not horizontally
  scalable as shipped.
- **Demo values in some templates.** Connector config templates need
  sanitization/parameterization for a Bosch environment.

## Verification evidence

Verified on Rancher Desktop (k3s):

- All three pods reached `1/1` Ready.
- The UI served HTTP `200` ("Connector Control Center") through the
  ingress.
- TLS was served with a certificate issued by the Solace Lab Intermediate
  CA.

Caveat: on the single-node laptop cluster the amd64 vendor images run
under QEMU emulation, which destabilized the control plane under load. A
stable interactive demo needs native/multi-arch images or more cluster
CPU. Running native amd64 on OpenShift avoids this emulation issue
entirely.

## Next steps

1. Provide the Bosch OpenShift registry and app domain; push the hardened
   `2.0.2-hardened` images with `hardened-images/build.sh` and set the
   `image.*.repository`, `route.uiHost`, `route.apiHost`, and external
   Postgres host in `values-openshift.yaml`.
2. Deploy on a native amd64 OpenShift cluster following
   `docs/OPENSHIFT-DEPLOYMENT.md`, injecting real secrets via
   `helm --set` from an untracked `.env`.
3. Confirm the Track 1 image deliverables with the Solace account team as
   the gate for production sign-off (see `docs/SECURITY.md`).

## Related documents

- `docs/OPENSHIFT-DEPLOYMENT.md` -- OpenShift deployment runbook.
- `docs/SECURITY.md` -- security posture and residual-risk register.
