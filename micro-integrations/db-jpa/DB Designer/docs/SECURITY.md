# DB Designer -- Security Posture

This document is a security posture statement for the **DB Designer**
(Connector Control Center) component of the Solace `db-jpa`
Micro-Integration, prepared for a customer security review and handover.

It describes the controls the Helm chart applies, how secrets and
network exposure are handled, the image supply chain, and an honest
residual-risk register. Where a control is partial or a risk is not yet
closed, this document says so rather than overstating the posture.

Scope: the deployment artifacts in
`micro-integrations/db-jpa/DB Designer/` -- the Helm chart under
`charts/db-designer/`, the hardened image overlays under
`hardened-images/`, and the deploy scripts under `scripts/`. It does
NOT cover the opaque internals of the Solace-provided application code
(see [Image supply chain](#image-supply-chain)).

## Component overview

The DB Designer is a three-workload web application:

| Workload | Image | Port | Exposure |
| --- | --- | --- | --- |
| `services` (Node backend) | `connector_designer_services` | 6002 | Ingress / Route (`apiHost`) |
| `ui` (React SPA) | `connector_designer_ui` | 6003 | Ingress / Route (`uiHost`) |
| `postgres` (metadata DB) | `postgres:13` (embedded) | 5432 | ClusterIP only |

The React UI calls the backend **from the browser**, so both the UI
host and the API host must be browser-resolvable. The chart therefore
exposes two distinct front doors (`uiHost` + `apiHost`) and nothing
else. Everything internal stays on `ClusterIP` Services.

Two deployment targets are supported by Helm overlays:

- `values-rancher.yaml` -- local lab (k3s / Rancher Desktop): nginx
  Ingress, cert-manager issuer `solace-lab-ca-issuer`, Kyverno-injected
  CA trust and registry pull secret, embedded Postgres `StatefulSet`.
- `values-openshift.yaml` -- customer target (OpenShift): Routes instead
  of Ingress, an **external / operator-managed Postgres**, the hardened
  images, and **no custom SCC**.

## Controls summary

Status legend: **Enforced** (applied by the chart on both targets),
**Enforced (OpenShift)** (relies on the hardened images / OpenShift
overlay), **Partial** (present but with a documented caveat).

<!-- markdownlint-disable MD013 -->

| Control | Status | Notes |
| --- | --- | --- |
| Non-root execution | Enforced (OpenShift) | Hardened images set `USER 1001`; the OpenShift overlay sets `runAsNonRoot: true` for app pods. On Rancher/k3s the un-hardened vendor images run as root (`runAsNonRoot: false`), tolerated locally only. |
| OpenShift arbitrary-UID support | Enforced (OpenShift) | Hardened images group-own runtime dirs to GID 0, make them group-writable, and set `HOME=/tmp`. Verified running as UID `26999:0`. Satisfies the default `restricted-v2` SCC -- no cluster-admin, no custom SCC. |
| Drop all Linux capabilities | Enforced | `securityContext.capabilities.drop: [ALL]` on every app container and on the embedded Postgres container, on both targets. |
| No privilege escalation | Enforced | `allowPrivilegeEscalation: false` on all app pods and Postgres; also enforced by the optional SCC. |
| No privileged / host access | Enforced | No `privileged`, no `hostNetwork`/`hostPID`/`hostIPC`, no host ports, no `hostPath` volumes. The optional SCC restates all of these as `false`. |
| seccomp RuntimeDefault | Enforced | `podSecurityContext.seccompProfile.type: RuntimeDefault` on app pods and Postgres. |
| Read-only root filesystem | Partial | `readOnlyRootFilesystem: false` -- the app writes to `/app/dist/bin/logs`, `/app/tmp`, and the download volume. Writes are confined to mounted volumes (see [Persistence](#persistence)); the base layers are not made read-only. |
| NetworkPolicy | Enforced | Default-deny baseline with an explicit allow-list; see [Network exposure](#network-exposure). Ingress from the ingress/route namespace and intra-release only. Egress is DNS plus unrestricted (broker + target DB reachability). |
| TLS in transit (edge) | Enforced | cert-manager-issued certs on nginx Ingress (Rancher) or edge-terminated Routes with `insecureEdgeTerminationPolicy: Redirect` (OpenShift). See [TLS](#tls-in-transit). |
| Secrets handling | Enforced | Sensitive values injected via `helm --set` from a gitignored `.env` into an `Opaque` Secret; only demo defaults are committed. See [Secrets](#secrets-handling). |
| Image provenance | Partial | Opaque Solace vendor images (no Dockerfile/source) with a thin, auditable hardened overlay we control. See [Image supply chain](#image-supply-chain). |
| Persistence | Enforced | Produced packages on an RWO PVC; logs/tmp/entity folders on `emptyDir`. Single-writer backend (`Recreate`). See [Persistence](#persistence). |

<!-- markdownlint-enable MD013 -->

## Secrets handling

The chart does not commit real secrets. The flow is:

1. Non-sensitive config lives in `values.yaml` and the overlays and is
   safe to commit (broker host, VPN name, ports, UUID, log retention).
2. Sensitive values live under the `secret:` block with **demo-only**
   defaults (for example `postgres`, `coeadmin`, `admin`). These are
   intentional placeholders, consistent with the rest of the repo, and
   are not production credentials.
3. At deploy time, `scripts/start.sh` sources a gitignored `.env`
   (template: `.env.example`) and injects any set values via
   `helm --set secret.<name>=<value>`, overriding the demo defaults.
4. The chart renders `templates/secret-env.yaml` -- an `Opaque`
   Kubernetes `Secret` -- assembling the backend dotenv consumed at
   `/app/dist/bin/.env`, plus a discrete `postgres-password` key that
   the Postgres `StatefulSet` reads via `secretKeyRef`.
5. The Secret is mounted read-only into the backend as a file
   (`subPath: .env`), not exposed as plain env vars in the pod spec.

The env template `.env.example` documents every overridable key
(`POSTGRES_PASSWORD`, `SOLACE_CLIENT_PASSWORD`, `SOLACE_MGMT_PASSWORD`,
`SOLACE_API_TOKEN`, `SECRET_APP_KEY`, `SECRET_REFRESH_KEY`,
`PASSWORD_ENCRYPTION_KEY`, `ADMIN_USER_PASSWORD`). For an existing,
externally managed Secret, set `secret.existingSecret` and the chart
will not create its own.

Gitignore hygiene: `*.env` (except `*.env.example`), large image
tarballs (`*.tar`), generated connector packages, and logs are
gitignored. Two files with more sensitive leftovers (a Solace Cloud
JWT and live EC2 Postgres credentials) live under already-gitignored
directories and must never be committed.

**Customer action:** provide real credentials only through `.env` /
`--set` or an `existingSecret`, and rotate the demo `appSecretKey`,
`appRefreshTokenKey`, and `passwordEncryptionKey` values, which govern
token signing and at-rest password encryption in the app.

## Network exposure

Only the UI and the API are reachable from outside the namespace. Both
front doors terminate TLS at the edge and forward plain HTTP to
`ClusterIP` Services inside the cluster. The Postgres metadata DB is
`ClusterIP` and is never exposed via Ingress or Route.

`templates/networkpolicy.yaml` applies a NetworkPolicy selecting all
release pods with `policyTypes: [Ingress, Egress]`:

- **Ingress allowed from:**
  - the ingress/route controller namespace
    (`networkPolicy.ingressNamespace`, default `ingress-nginx`) --
    this is what reaches the UI and API; and
  - other pods of the same release (intra-release: UI -> API,
    API -> Postgres).
  - All other ingress is denied.
- **Egress allowed to:**
  - DNS (UDP/TCP port 53) to any namespace; and
  - everything else (`- {}`) -- deliberately open so the backend and
    the in-pod meta-api can reach the Solace broker and arbitrary
    **target databases** the operator introspects.

The open egress rule is a functional requirement (the Designer connects
to operator-chosen databases and brokers that are not known at deploy
time), not an oversight. If customer policy requires egress restriction,
it should be scoped to the known broker and database CIDRs for the
specific deployment; the chart does not do this by default.

On OpenShift, `networkPolicy.ingressNamespace` must be set to the
router's namespace (typically `openshift-ingress`) so Routes can reach
the pods.

## TLS in transit

- **Rancher / nginx:** `templates/ingress.yaml` requests two
  cert-manager certificates (`db-designer-ui-tls`,
  `db-designer-api-tls`) from the `solace-lab-ca-issuer` cluster issuer,
  with `ssl-redirect: "true"`. Verified in the lab: the certificate
  chained to the Solace Lab Intermediate CA and the UI served HTTP 200.
- **OpenShift:** `templates/route.yaml` creates edge-terminated Routes
  with `insecureEdgeTerminationPolicy: Redirect`, so HTTP is redirected
  to HTTPS and TLS is terminated by the OpenShift router.

In both cases traffic **inside** the cluster (edge -> Service -> pod,
and UI -> API -> Postgres) is plain HTTP / unencrypted Postgres
protocol, relying on the cluster network and the NetworkPolicy rather
than in-cluster mTLS. This is standard for edge-terminated ingress but
is called out explicitly for the reviewer.

## Image supply chain

The application images are **opaque Solace vendor images**: no
Dockerfile or source is provided, so we cannot audit or rebuild their
contents. We control only a thin overlay on top of them.

**What we control (auditable in this repo):**

- `hardened-images/Dockerfile.services` and `Dockerfile.ui` -- short,
  reviewable overlays that add non-root `USER 1001`, group-0 ownership
  and group-write on the runtime-writable directories, and `HOME=/tmp`
  for OpenShift arbitrary-UID compatibility. They do **not** modify the
  application or the base runtime.
- `hardened-images/build.sh` -- builds and optionally pushes the
  overlays with tag `2.0.2-hardened`.
- `hardened-images/Dockerfile.artifacts-seed` -- multi-stage seed
  image that builds the DB CLI **from source** (`mvn verify` as a
  gate) at image-build time, so a distribution can never carry a
  stale CLI jar. The seed initContainer logs the jar's sha256 at pod
  start (runtime provenance).
- `release/package-release.sh` -- produces the versioned customer
  distribution bundle. Its `MANIFEST.txt` records bundle version, git
  SHA, build date, image IDs, and sha256 sums of every file --
  verifiable provenance without any registry infrastructure.
- The Helm chart: security contexts, NetworkPolicy, TLS, Secret
  assembly, probes, and resource limits.

**What we do NOT control:**

- The base OS, package set, and application code inside the vendor
  images -- opaque, unscanned by us, and not reproducible from source.
- The runtime version (Node `16.20.2`) and architecture (amd64-only)
  baked into those images -- fixed by the vendor and accepted as-is;
  the customer image scanner should be run against them.

Verified: running the hardened images as an arbitrary UID (`26999:0`)
starts cleanly with Node `v16.20.2` and writable runtime dirs, and they
satisfy OpenShift's default `restricted-v2` SCC -- so no cluster-admin
and **no custom SCC** are required on OpenShift. By contrast, the
un-hardened vendor images run as root and would require
`openshift.scc.create=true`, which ships a `RunAsAny` SCC bound to the
release ServiceAccount and needs cluster-admin to install. That path is
off by default and should not be used in customer production.

**Customer action:** verify the bundle against `MANIFEST.txt`
(sha256), push the images into the customer registry with
`scripts/load-and-push.sh`, set the printed `image.*` /
`servicesApp.artifacts.seedImage` values plus a matching
`imagePullSecrets`, and run the customer's image scanner against
them. Note the scanner may flag the underlying vendor base image,
which the thin overlay cannot change.

## Persistence

- **Produced connector packages** are written to an RWO PVC
  (`-binary-downloads`, `ReadWriteOnce`), mounted at
  `/app/tmp/binary/download`. RWO plus the `Recreate` deployment
  strategy keeps a single writer; the backend is intentionally a single
  replica.
- **Logs, scratch, and entity folders** (`/app/dist/bin/logs`,
  `/app/tmp`) are `emptyDir` -- ephemeral, discarded with the pod.
- **Embedded Postgres** (Rancher only) uses a `ReadWriteOnce`
  `volumeClaimTemplate` and runs as its own fixed UID (999) with a
  matching `fsGroup` so the official image never needs `CAP_CHOWN`
  (which we drop). On OpenShift the recommended configuration is
  `postgres.embedded=false` with an external / operator-managed
  Postgres, because the official `postgres:13` image's pinned UID 999
  is rejected by `restricted-v2`.

## Residual risk register

These are known, unmitigated or partially mitigated risks at handover.
Severity is a qualitative assessment for a customer production context.
Ownership indicates who acts to close the risk.

<!-- markdownlint-disable MD013 -->

| # | Risk | Severity | Mitigation / ownership |
| --- | --- | --- | --- |
| R1 | Demo credentials committed as chart defaults (`postgres`, `coeadmin`, `admin`, `TEST`, `solace`). Harmless only if overridden. | Medium | Inject real values via `.env` / `--set` or `existingSecret`; rotate signing/encryption keys. Owner: customer at deploy. |
| R2 | Config templates carry DEMO credentials (`admin`/`coeadmin`/`test123@!`/`pass`, jasypt key). The vendor demo external IPs were replaced with RFC-2606 `.example` placeholders and the sink dialect mix fixed, so nothing external-infra-revealing remains. | Low | Override the credentials via `.env` / `--set` / `existingSecret` at deploy and rotate the jasypt key; set the real broker/DB hosts. Owner: customer at deploy. |
| R3 | No HA: single backend replica with `Recreate` and an RWO package PVC; a node/pod failure means downtime until reschedule. | Low | Acceptable for a design-time tool (not a data-plane runtime). Owner: operator if HA is required. |
| R4 | Open egress by NetworkPolicy: `egress: - {}` permits the backend to reach any host (required to introspect operator-chosen DBs/brokers). | Low | Scope egress to known broker/DB CIDRs if customer policy requires. Owner: operator. |
| R5 | Edge-only TLS: in-cluster hops (edge -> Service, UI -> API -> Postgres) are unencrypted, relying on NetworkPolicy and the cluster network. | Low | Add a service mesh / in-cluster TLS if required by customer policy. Owner: operator. |
| R6 | Package download: a vendor hang made the browser download unreliable. `getEntityColumns()` settles its Promise only from inside a `forEach`, so for a flow with a data-transformation mapper it never resolves when the entity file is not at the expected flat path -- the whole download hangs indefinitely. Separately, the download returns the whole package base64-in-JSON, so the ~108MB static core jar makes a ~150MB / ~15s response. | Low | Fixed in the startup patch: `getEntityColumns` is replaced with a version that reads the flat entity tree, searches recursively, and always resolves. With that fixed the download is left fully open (the UI selection is honoured as-is) and every combination completes within the client timeout -- verified end-to-end: config+entity 200/633ms, full package incl. core jar 200/~150MB/~14.9s (emulated lab; faster on native amd64). Backend memory is 4Gi with a `NODE_OPTIONS` heap cap. The base64-in-JSON size is the vendor's current download design and is accepted as-is. |
| R7 | Runtime Maven fetch: the connector `entity.jar` build pulls its deps from Maven Central at request time (`/root/.m2` is empty on a fresh pod), which would fail on air-gapped clusters and on OpenShift arbitrary UID (`user.home=/` not writable). | Low | Mitigated: the seed image bakes a complete `m2-repository` and the chart pins `maven.repo.local` (MAVEN_OPTS) and forces `--offline` (MAVEN_ARGS), so the build is air-gap-safe and works under an arbitrary UID. |

<!-- markdownlint-enable MD013 -->

## Verification evidence

Verified on Rancher Desktop (k3s):

- All three pods (`services`, `ui`, `postgres`) reached `1/1` Ready.
- The UI served HTTP 200 ("Connector Control Center") through the nginx
  Ingress.
- TLS certificates were issued by the Solace Lab Intermediate CA via
  `solace-lab-ca-issuer`.
- The hardened images ran as arbitrary UID `26999:0` with Node
  `v16.20.2` and writable runtime dirs, satisfying `restricted-v2`.

Caveat: the amd64 images under QEMU emulation on the single-node laptop
cluster destabilized the control plane under sustained load. A stable
interactive deployment needs to run on native amd64 or with more cluster
CPU; native amd64 on OpenShift avoids the emulation issue entirely.
