# Track AKS: running the EuroCIS demo stack on Azure Kubernetes Service

Track: run the whole "Preis- und Aktionsagent mit Freigabe" stack (SAM
2.542.1 + GEBIT-style gRPC POS simulator + loyalty service + BFF/UIs +
broker + Postgres) on AKS for EuroCIS 2027 (16.-18.02.2027), developed
first on the local lab. Written 2026-11-10. Read-only research: no
cluster, broker, DB, Docker or repo change. Local experiments only in
`impl/aks/` (Helm render of the SAM chart, YAML sketches).

Notation: **[V]** = verified (file:line, command output or URL),
**[A]** = assumption / needs a Gate-0 check. `AMD/` =
`REPO/agent-mesh-deployment/`, `EMD/` = `REPO/event-mesh-deployment/`,
`INFRA/` = `~/Documents/GitHub/solace-lab-infrastructure/`, `CHART/` =
`~/.local/share/sam/charts/solace-agent-mesh-2.3.10/`, `IMPL/` =
`.../scratchpad/impl/`.

Artifacts produced (sketches, nothing applied anywhere):

- `IMPL/aks/sam-values-aks.yaml` -- Helm overlay on top of
  `AMD/local-k8s-values.yaml`; renders cleanly with chart 2.3.10 incl.
  its strict schema (`helm template`, rc=0, 17 objects, all images from
  ACR, workload-identity label on gwe/awe/str) [V: `IMPL/aks/rendered-aks.yaml`;
  not versioned, regenerate with `helm template`,
  `AKS-MIGRATION-PLAN.md:1601`]
- `IMPL/aks/ingress-nginx-values-aks.yaml`, `ingress-grpc-example.yaml`,
  `clusterissuer-letsencrypt-dns.yaml`, `pubsubplus-values-aks.yaml`
  (YAML-parsed OK), `az-foundation.sketch.sh` (`bash -n` OK, never run)

---

## 0. Executive summary

- **Recommendation:** one AKS **Standard-tier** cluster, Kubernetes
  **1.36** (same minor as the lab's k3s 1.36.3; AKS GA Jun 2026, EOL
  Jun 2027 [V: MS support calendar]), region **Germany West Central**,
  one node pool **2 x Standard_D8as_v6** (8 vCPU / 32 GiB each, amd64,
  single AZ), Azure CNI Overlay. In-cluster: SAM 2.542.1 (chart 2.3.10
  from the offline package, images in **ACR**), **ingress-nginx 1.15.1
  self-installed on an internal LB** (same as lab), cert-manager with
  **Let's Encrypt DNS-01 on Azure DNS**, **Keycloak** (same realm and
  scripts as the lab), **one PubSub+ Standard broker** (Helm chart,
  VPNs `default` + `sam`), our demo services (gpos-pos gRPC sim,
  loyalty gRPC, engine/MCP, BFF/UI), lean Prometheus/Grafana/Loki.
  Managed: **Azure Database for PostgreSQL Flexible Server 18** (all
  Postgres data: gpos, loyalty, Keycloak, SAM platform/webui/
  orchestrator) and **Azure Blob** for SAM artifacts (the chart has no
  Postgres option for artifacts).
- **Booth access:** nothing booth-facing is public. The booth router
  (RUTX50) builds a **WireGuard tunnel to a tiny gateway VM in the AKS
  VNet**; kiosks, tablet (SAM HITL inbox), monitor, ESP32 MQTT and the
  developer Macs reach the internal LB through it. Public DNS names
  with publicly trusted certificates resolve to private IPs, so iPads
  need no lab-CA profile. Optional public gRPC endpoint for the GEBIT
  lab later (mTLS + IP allowlist).
- **Cost (list price, EUR, excl. VAT and LLM tokens):** ~**EUR 860 per
  month at 24/7** (~EUR 28/day); ~**EUR 2.0-3.0k** for the whole period
  Nov 2026 - Feb 2027 with nightly/weekend stops during build-up.
- **Effort:** **~14 person-days** for the full path (foundation, add-ons,
  broker, Keycloak, SAM, images, overlays, tunnel, hardening, drills);
  ~9-10 PT minimal path (everything in-cluster, no tunnel, public
  allowlisted ingress). Fits G0-G2 if started in G0.
- **Top AKS risks:** ingress-nginx is upstream end-of-life (no fixes
  since March 2026) and the AKS managed NGINX add-on loses support in
  Nov 2026; SAM chart only renders `Ingress` and derives `https` URLs
  only from `ingress.tls`, so Gateway API needs a workaround; lab
  scripts hard-code `registry.solace.lab`, pull secret, Kyverno CA
  trust, CoreDNS NodeHosts patch and `sam.solace.lab`; Azure LB 4-min
  idle timeout vs. 900 s MCP calls and SSE; ingress default 1 MiB body
  limit vs. multi-modal uploads (also in the lab); pubsubplus chart
  defaults to a PUBLIC LoadBalancer; subscription governance/quota;
  auto-upgrades during the fair; Messe network may block UDP (WireGuard).

---

## 1. What the local lab stack is, and what must exist on AKS

### 1.1 Lab inventory (verified read-only on 2026-11-10)

| # | Lab component | Where / version | Source |
|---|---|---|---|
| 1 | Kubernetes | Rancher Desktop k3s `v1.36.3+k3s1`, 1 node, **arm64**, Docker runtime shared with host | [V: `kubectl get nodes -o wide`] |
| 2 | SAM v2 | chart `solace-agent-mesh` 2.3.10, app 2.542.1, str 1.80.2, ns `sam-solace-lab`, release `agent-mesh`; pods gwe/awe/str + bundled `postgresql` (18.0) + `seaweedfs` on `local-path` PVCs 10Gi/20Gi | [V: `helm list -A`, `kubectl get pods,pvc`] |
| 3 | SAM DBs | `sam-solace-lab_{orchestrator,webui,platform}`, only `plpgsql`, 8-15 MB each | [V: read-only `psql` in pod] |
| 4 | Ingress | ingress-nginx chart 4.15.1 / controller 1.15.1, class `nginx`, Service `LoadBalancer`, no global ConfigMap tuning | [V: `helm list`, cm `ingress-nginx-controller` data empty] |
| 5 | PKI | cert-manager v1.20.2, trust-manager v0.22.0, ClusterIssuer `solace-lab-ca-issuer`, Kyverno 1.17.1 policies (`inject-solace-lab-ca-trust-bundle`, `ingress-require-tls` incl. mandatory ssl-redirect annotation, `cert-restrict-domain`, `cert-require-ecdsa`, ...) | [V: `helm list`; `INFRA/pki/manifests/04-kyverno-policies.yaml:34-529`] |
| 6 | Registry | `registry:2` at `registry.solace.lab` (ns `oci`), Kyverno `inject-registry-pull-secret` / `sync-registry-pull-secret` | [V: `INFRA/registry/manifests/02-registry.yaml:52`, `04-kyverno-policies.yaml:52,101`] |
| 7 | IdP | Keycloak `quay.io/keycloak/keycloak:26.2` + `postgres:17-alpine` (ns `iam`), realm `solace-lab`, host `auth.solace.lab` | [V: `INFRA/keycloak/manifests/03-keycloak.yaml:141`, `02-postgres.yaml:54`] |
| 8 | Broker | `solace-1` in host Docker, `solace/solace-pubsub-standard:latest` = **10.25.0.208 arm64**, VPNs `default` (MQTT 1883), `sam` (SMF 55557, WS 8008, AMQP 5673 for tracing), `amartens-test`; scaling 1000 conns, spool 30 GB; plus `solace-2`, DMR, EMA, OTel collector | [V: `docker inspect`, `EMD/docker-compose.yaml`, `EMD/terraform/broker_solace_1.tf`, `EMD/config/solace-1/solace_config_keys.env`] |
| 9 | Demo Postgres | host Docker `postgres:latest` = **18.3**, port 5432 (+ pgadmin 5433) | [V: `docker exec postgres postgres --version`] |
| 10 | Observability | kube-prometheus-stack 83.5.0, Loki 6.55.0, Tempo 2.0.0, Alloy 1.11.0; SAM ServiceMonitors/alerts/dashboards from `AMD/manifests/observability/` | [V: `helm list`] |
| 11 | DNS | `/etc/hosts` + CoreDNS NodeHosts patch by `AMD/scripts/start.sh:139-146` (SAM self-calls `sam.solace.lab`) | [V] |
| 12 | LLM | LiteLLM proxy `https://lite-llm.mymaas.net`, public DNS (AWS IP ranges 3.221.x / 34.198.x / 98.94.x), `/health/liveliness` 200 in 0.5 s from the lab Mac | [V: `dig`, `curl`] |
| 13 | SAM lab sizing | idle: gwe 315Mi, awe 444Mi, str 941Mi, postgres 140Mi, seaweedfs 139Mi; node 2.5 cores / 18 GiB used overall (many other lab apps) | [V: `kubectl top`] |

### 1.2 What the demo needs on AKS (and what not)

Needed (the demo's runtime closure):

- SAM 2.542.1 platform (gwe, awe, str) + its persistence + the
  DB-managed content (`provision.sh`: RBAC incl. `notify:_:send` for
  `power_user`, model aliases `fast`/`workflow`/`expert`/`general`,
  max_tokens; developer-mcp optional) + the demo's `mesh/` package
  (event_mesh entrypoint, workflows, agents, connector with static
  `manifest:`).
- Our services: `gpos-pos` (GEBIT-style gRPC Purchase sim + HTTP
  gateway), loyalty service (gRPC), `gpos-engine` (MCP :8765,
  state/rules), `gpos-ui` (BFF + SSE, monitor/kasse/tablet pages).
- Broker with VPN `sam` (all booth topics, SAM) and VPN `default`
  (ESP32 label hints, if labels stay in scope).
- Postgres (constraint 6: all demo data in Postgres).
- OIDC IdP with the same demo identities (`power_user@solace.lab`
  receives the HITL notifications; `sam_admin@solace.lab` for
  provisioning).
- Ingress + TLS, DNS, registry, minimal monitoring.

Not needed on AKS: `solace-2`, DMR, Event Management Agent / Event
Portal, VPN `amartens-test`, OTel collector + Tempo (SAM emits no spans;
broker tracing optional), trust-manager + Kyverno (see 1.3), `registry:2`,
db-designer, mi-solace-lab, the declarative lab agents in
`sam-solace-lab-agents`, pgadmin (use a throwaway `psql` pod), the
CoreDNS NodeHosts hack, the SAM desktop wiring.

### 1.3 Replacement matrix (lab -> AKS)

| Lab piece | AKS recommendation | Alternative(s) | Why |
|---|---|---|---|
| k3s 1.36 arm64 single node | AKS Standard tier 1.36, 2 x D8as_v6 amd64, 1 AZ | 3 x D4as_v6; arm64 Cobalt `D8ps_v6` (EUR 0.30/h vs 0.39/h, same arm64 images as lab) | amd64 matches the later GEBIT handover; arm64 is cheaper and gives image parity [V: retail prices API] |
| ingress-nginx 1.15.1 | **same, self-installed, pinned, internal LB** | AKS App Routing **Gateway API** (`approuting-istio`, GA 2026) ; App Gateway for Containers | identical annotations/manifests; SAM chart only renders `Ingress` (see 2.4) |
| cert-manager + lab CA + trust-manager + Kyverno CA injection | cert-manager + **Let's Encrypt DNS-01 (Azure DNS, workload identity)**; no custom CA needed anywhere | keep lab CA: SAM `samDeployment.customCA` + `truststore` ConfigMap, kiosk CA profiles | public trust removes the CA injection, the JVM truststore issue (Keycloak) and the iPad CA profile |
| `registry.solace.lab` + Kyverno pull secret | **ACR Basic** attached to AKS (`--attach-acr`, kubelet AcrPull) -> no pull secret | ACR Standard (100 GiB) | chart validation fails if a listed pull secret is missing -> overlay sets `global.imagePullSecrets: []`. Superseded 18.11.2026 (überholt): pull token instead of `--attach-acr`, overlay sets `["acr-pull"]`, see `AKS-MIGRATION-PLAN.md` AKS-E21 |
| Keycloak 26.2 + own Postgres (ns `iam`) | **Keycloak 26.x in-cluster**, DB on PG Flexible, host `auth.<domain>`; same realm/scripts | Entra ID (`providerName` default `azure`, `claimKey: roles`) | demo identities, RBAC claim mappings and `defaultUserIdentity` stay unchanged; corporate MFA/conditional access on shared booth tablets is a show risk; Entra app registration needs tenant admin |
| solace-1 (Docker) | **PubSub+ Standard 10.25.0.208 via `solacecharts/pubsubplus`**, `redundancy: false`, ClusterIP + internal LB for booth MQTT; VPNs/clients via the existing Terraform modules | Solace Cloud service in Azure GWC | parity (two VPNs, same ports), free edition, no extra network hop; Solace Cloud gives one VPN per service (two services or a VPN redesign) |
| host Docker Postgres 18.3 + SAM bundled Postgres 18.0 | **Azure DB for PostgreSQL Flexible Server 18**, Burstable B2ms, VNet-integrated | in-cluster Postgres StatefulSet (+ SAM bundled persistence) | survives cluster rebuilds/stops, PITR backups, start/stop; PG 18 GA on Flexible since Nov 2025 [V: MS release notes] |
| SAM SeaweedFS | **Azure Blob** (`dataStores.objectStorage.type: azure`, workload identity) | keep bundled SeaweedFS (then SAM DB must stay bundled too, see 2.3) | chart couples DB and object store in one switch |
| kube-prometheus-stack + Loki + Tempo + Alloy | lean kube-prometheus-stack + Loki single binary + Alloy, 7 d retention; reuse `AMD/manifests/observability/` | Azure Managed Prometheus + Managed Grafana; Container Insights off | same dashboards; low cost |
| `/etc/hosts` + CoreDNS NodeHosts | **Azure DNS public zone**, A records -> internal LB IP | router dnsmasq overrides only | AKS CoreDNS ConfigMap is add-on managed; in-cluster traffic to LB IPs is short-circuited by kube-proxy, so no hack is needed [A: verify `curl https://sam.<domain>` from a pod] |
| LiteLLM proxy | unchanged, egress via AKS outbound public IP | NAT gateway for a dedicated fixed IP | proxy is public; ~100 ms extra RTT per call from Frankfurt to AWS us-east [A] |

---

## 2. SAM chart 2.3.10 on AKS (what changes, verified against the chart)

### 2.1 Values that are lab-specific today

- `AMD/local-k8s-values.yaml:23` `sam.dnsName: sam.solace.lab`;
  `:68` broker `ws://host.docker.internal:8008`; `:124`
  `cert-manager.io/cluster-issuer: solace-lab-ca-issuer`; `:147`
  `global.imagePullSecrets: [registry-pull-secret]`; `:165-233` six
  image blocks pinned to `registry.solace.lab`; `:26` checked-in
  `sessionSecretKey` (generate a new one for AKS) [V].
- `AMD/scripts/start.sh:10` hard-codes `SAM_DNS_NAME`, `:131` applies
  the lab-CA Certificate, `:139-146` patches CoreDNS NodeHosts and
  restarts CoreDNS -- on AKS the `coredns` ConfigMap is reconciled by
  the add-on manager (custom entries belong in `coredns-custom`) and
  the step is unnecessary [A: AKS CoreDNS customization doc].
- `AMD/scripts/load-images.sh:42` `REGISTRY="registry.solace.lab"` and
  refuses other registries [V: CLAUDE.md].
- `provision.sh:36` `SAM_URL="https://sam.solace.lab"`,
  `lib/common.sh:21` auth cache `solace-lab.json`, `setup-keycloak-client.sh:22`
  `SAM_DNS_NAME="sam.solace.lab"`, `rbac/apply-rbac.sh:24` [V: grep].
  Keep the user identities `*@solace.lab` on AKS: they are only
  Keycloak email attributes, and RBAC manifests plus the entrypoint
  `defaultUserIdentity` reference them.

Consequence: an **AKS profile** is needed in `agent-mesh-deployment`
(env-parametrised `SAM_DNS_NAME`, `SAM_URL`, `SAM_TARGET`, registry,
`VALUES_OVERLAY`, skip NodeHosts when not k3s), plus
`load-images.sh` with `REGISTRY` from `.env.aks`. Estimated 0.5 PT,
owner decision because `agent-mesh-deployment` is shared infrastructure.

### 2.2 Overlay (sketch, renders) -- `IMPL/aks/sam-values-aks.yaml`

Applied as a second `-f` after the lab values (Helm replaces lists, so
`imagePullSecrets: []` wins). Key content:

- `sam.dnsName` / `ingress.host` / `ingress.tls` -> `sam.<domain>`,
  issuer `letsencrypt-dns`, all lab annotations kept (900 s timeouts,
  16k buffers) plus **`proxy-body-size: 100m`** (see 5, R7).
- `broker.url: tcp://solace-pubsubplus.solace.svc.cluster.local:55555`,
  dedicated client user `sam` (password from `.env.aks`), VPN `sam`.
- `global.persistence.enabled: false`, `namespaceId: sam-solace-lab`
  (kept: topic prefix and mesh manifests unchanged),
  `global.imagePullSecrets: []` (superseded 18.11.2026: `["acr-pull"]`
  with a pull token, see `AKS-MIGRATION-PLAN.md` AKS-E21).
- `dataStores.database.{host,port,adminUsername,adminPassword,applicationPassword}`
  for PG Flexible; `dataStores.objectStorage.type: azure`,
  `workloadIdentity.enabled: true`, `dataStores.azure.accountName`,
  `containerName`/`connectorSpecContainerName: sam-artifacts`.
- `samDeployment.serviceAccount.name` (required by the chart when
  workload identity is on [V: `CHART/templates/_validations.tpl:58`])
  plus annotation `azure.workload.identity/client-id`.
- image `registry: <acr>.azurecr.io` for gwe, str, dbInit (s3Init
  unused); awe limit 3Gi, str limit 6Gi (multi-modal tools:
  LibreOffice/ffmpeg/Chromium are str's heaviest per SAM docs).

Render result [V: `helm template`, rc=0]: images
`<acr>/solace-agent-mesh:2.542.1`, `<acr>/solace-agent-mesh-str:1.80.2`,
`<acr>/postgres:18.0-trixie` (db-init); no s3-init (gated by
`global.persistence.enabled`, `CHART/config/gwe/01-s3-init.initContainer.tpl:1`);
`OBJECT_STORAGE_TYPE: azure`; label `azure.workload.identity/use: "true"`
on gwe/awe/str pods. The sam-doctor hook gets its own SA with the
webhook label -- its storage check may warn (warn-only) [A].

### 2.3 External persistence: facts from the chart

- Bundled vs. external is **all-or-nothing** for DB and object store:
  `sam.objectStorage.type` is forced to `s3` when
  `global.persistence.enabled` is true (`CHART/templates/_helpers.tpl:192-194`),
  and the schema forbids `dataStores.*` credentials in bundled mode
  (`CHART/values.schema.json:567-600`) [V]. So "PG Flexible for SAM"
  implies "Azure Blob for SAM artifacts".
- `global.persistence` in the parent schema only allows `namespaceId`
  and `enabled` (`additionalProperties: false`), but `persistence-layer`
  is free-form, so in bundled mode a storage class goes into
  `persistence-layer.postgresql.persistence.storageClassName` /
  `persistence-layer.seaweedfs.persistence.storageClassName` (the
  chart validates the class exists) [V: schema walk, `_validations.tpl:164-180`].
- `dataStores.database.applicationPassword` is mandatory externally
  (`_helpers.tpl:185-186`) and **cannot be changed after first install**
  (db-init only creates missing users) [V: chart + SAM production doc].
- db-init uses `psql` with admin creds to `CREATE USER`/`CREATE
  DATABASE`/`GRANT` -- works with the Azure Flexible admin
  (`azure_pg_admin`, not superuser, but owns the DBs it creates); no
  extensions are needed (lab DBs only have `plpgsql`) [V for the lab;
  A for Azure]. DSNs are `postgres://...` without `sslmode`; pgx and
  libpq default to `prefer`, which negotiates TLS, so Azure's
  `require_secure_transport` is satisfied [A: G0 check].
- The `postgres` image is still pulled for db-init with an external DB
  (SAM air-gap doc) -> mirror it to ACR [V: `installing__kubernetes__airgap.md`].
- Grafana datasource `AMD/manifests/observability/grafana-datasource-sam-platform-config.yaml:28`
  points at `agent-mesh-postgresql.sam-solace-lab:5432` -> AKS overlay
  points it at the Flexible server with `sslmode: require`.

### 2.4 Ingress API vs Gateway API for SAM

- The chart renders only `networking.k8s.io/v1 Ingress`
  (`CHART/templates/ingress.yaml`) [V].
- External URLs (OIDC callback, frontend, platform) get `https` only
  when `ingress.enabled` AND `ingress.tls` is non-empty, else from
  `service.tls.enabled` (`CHART/templates/_config_helpers.tpl:19-54`) [V].
  With a Gateway API route and `ingress.enabled: false`, SAM would emit
  `http://` URLs and the OIDC redirect breaks -- workarounds are a
  dummy IngressClass (chart validates the class exists) or
  `service.tls.enabled` with TLS re-encryption at the gateway. This is
  the main reason to stay on an Ingress-API controller for the fair.
- SAM docs require ingress/LB timeouts >= 120-180 s for synchronous
  deploy calls; the lab uses 900 s for MCP `tools/call`
  [V: `installing__kubernetes__production.md`, `AMD/local-k8s-values.yaml:120-123`].

### 2.5 SAM runtime notes that matter on AKS

- Notification service (HIL delivery surface) is on by default and
  reuses the platform DB (`NOTIFY_DATABASE_URL` defaults to
  `PLATFORM_DATABASE_URL`) [V: `/etc/sam/configs/gwe/platform.yaml:31-46`
  in the lab gwe pod]. Nothing extra on AKS. If an e-mail channel is
  ever used: Azure blocks outbound TCP 25 -> relay on 587 [A].
- Platform service blocks private-network addresses for MCP discovery
  unless `SAM_PLATFORM_ALLOW_PRIVATE_MCP=true`; the lab works without
  it because connectors carry a static `manifest:` (no discovery) and
  tools execute from awe/str [V: SAM air-gap doc; lab env cm has no such key].
  Keep the generated manifest on AKS; do not set the flag.
- Each component is a single replica; scale = bigger limits. After a
  simultaneous gwe+awe restart (cluster stop/start!) restart awe once
  more after gwe is ready [V: `AMD/README.md` Observability notes].
- Product analytics: with internet egress on AKS the release may send
  anonymous usage data; decide `sam analytics disable` [V: air-gap doc].

---

## 3. Offline package and images (ACR, multi-arch)

### 3.1 Vendor images

- The 2.542.1 package ships per-arch **docker-save archives**
  (`manifest.json` with `RepoTags`, e.g.
  `docker.io/chrislusf/seaweedfs:4.48-compliant`; no OCI index) in
  `Images/amd64/` and `Images/arm64/` [V: `tar -t` listing of
  `seaweedfs-4.48-compliant-amd64.tar.gz`]. Sizes amd64 (gz): app
  0.95 GB, str 1.58 GB, postgres 0.16 GB, seaweedfs 0.13 GB, embedded
  broker 0.59 GB [V: `ls -la`].
- AKS (amd64) needs only `solace-agent-mesh:2.542.1`,
  `solace-agent-mesh-str:1.80.2`, `postgres:18.0-trixie` (db-init);
  seaweedfs only in bundled mode; the embedded broker never.
- `az acr import` cannot read tarballs. Recommended path, which does
  NOT touch the Rancher Desktop Docker daemon (it is shared with k3s
  and subject to kubelet image GC [V: CLAUDE.md]):

  ```bash
  az acr login -n <acr>            # or: crane auth login <acr>.azurecr.io
  gunzip -c Images/amd64/solace-agent-mesh-2.542.1-app-amd64.tar.gz > /tmp/app.tar
  crane push /tmp/app.tar <acr>.azurecr.io/solace-agent-mesh:2.542.1
  # same for str 1.80.2 and postgres 18.0-trixie; or
  # skopeo copy docker-archive:/tmp/app.tar docker://<acr>.azurecr.io/solace-agent-mesh:2.542.1
  ```

  Verify each file against the package `bom.yaml` checksums first (SAM
  air-gap procedure). One-time upload ~2.7 GB gz [A: crane/skopeo need
  the uncompressed archive -> gunzip first]. A `load-images.sh`
  variant with `REGISTRY=<acr>.azurecr.io` and `ARCH=amd64` keeps the
  values file as single source of truth for pins.
- ACR Basic includes 10 GiB storage (EUR 0.15/day); SAM amd64 ~2.7 GB
  compressed plus our images fit. Standard (EUR 0.60/day, 100 GiB) only
  if several SAM versions accumulate [V: retail prices API].
- Broker image: mirror `solace/solace-pubsub-standard:10.25.0.208`
  (multi-arch on Docker Hub; the lab runs it as `latest`) into ACR and
  pin the tag -- avoids Docker Hub rate limits and silent upgrades.

### 3.2 Our own images (Mac arm64 dev, AKS amd64)

- Keep the lab loop fast: native arm64 `docker build` + push to
  `registry.solace.lab` (BSG Makefile pattern, `REPO/bsg-trading-desk-demo/Makefile`).
- Release points (end of each gate): `docker buildx build --platform
  linux/amd64,linux/arm64 -t <acr>.azurecr.io/gpos-demo/gpos-demo:<semver>
  --push app/` -- one multi-arch index, same tag as the lab. The image
  is Python 3.12-slim with wheels (grpcio, protobuf, psycopg[binary],
  Pillow, solace-pubsubplus) that exist for both arches, so QEMU
  emulation only slows `pip install` [A]. Fallback without emulation:
  `az acr build --platform linux/amd64` (ACR Tasks, per-second billing).
- The amd64 variant is also what GEBIT's Kubernetes needs after the
  fair (DESIGN 4.7).
- GEBIT descriptor sets stay out of every image and the repo; on AKS
  they are mounted from a Secret/ConfigMap created by `install.sh`
  from `GEBIT_DESCRIPTOR_DIR` (DESIGN 4.2).
- Kustomize `images:` per overlay: lab `registry.solace.lab/...`, aks
  `<acr>.azurecr.io/...`.

---

## 4. gRPC endpoints and browser UIs on AKS

### 4.1 Traffic paths

```text
 booth LAN 192.168.50.0/24 --WireGuard--> wg VM 10.20.9.4 (SNAT)
     |                                        |
     |                     internal LB 10.20.0.250 (ingress-nginx, TLS)
     |                       sam.<d>     -> gwe :80        (HTTP, SSE)
     |                       auth.<d>    -> keycloak       (HTTP)
     |                       gpos.<d>    -> gpos-ui (BFF)  (HTTP, SSE, uploads)
     |                       pos-grpc.<d>     -> gpos-pos :50051     (gRPC h2c)
     |                       loyalty-grpc.<d> -> loyalty :50052      (gRPC h2c)
     |                       grafana.<d> -> grafana
     |                     internal LB 10.20.0.251: MQTT 1883 (VPN default, ESP32)
 in-cluster (no ingress hop):
   gpos-ui BFF -> gpos-pos.gpos-demo.svc:50051 (gRPC plaintext)
   gpos-engine MCP :8765 <- awe/str (connector, static manifest)
   all apps -> solace-pubsubplus.solace.svc:55555 (SMF), VPN sam
   all apps -> <pg>.postgres.database.azure.com:5432 (TLS, private DNS)
```

### 4.2 gRPC through ingress-nginx (sketch `IMPL/aks/ingress-grpc-example.yaml`)

- One `Ingress` per gRPC host with
  `nginx.ingress.kubernetes.io/backend-protocol: "GRPC"`; do not mix
  it into the BFF's Ingress (annotation is per Ingress object).
- TLS terminates at the ingress (HTTP/2 via ALPN; `use-http2` is the
  controller default), backend is plaintext h2c on the pod port; Service
  port `appProtocol: kubernetes.io/h2c`.
- Long-lived/streaming RPCs: `proxy-read-timeout`/`proxy-send-timeout`
  3600 (ingress-nginx applies them to the gRPC location [A: verify with a
  streaming call]), client keepalive pings, Azure LB idle timeout 30 min.
- Health: native Kubernetes `grpc:` readiness probe (gRPC health
  protocol), and server reflection on, so `grpcurl
  pos-grpc.<domain>:443 list` works in the Tiefenecke.
- If GEBIT (G3) must call our endpoint from outside: second controller
  class `nginx-public` on a public LB (`externalTrafficPolicy: Local`)
  carrying ONLY the gRPC Ingresses, with mTLS
  (`auth-tls-secret`, `auth-tls-verify-client: "on"`) and
  `whitelist-source-range` for GEBIT's egress IPs. Not needed for the
  booth itself.
- Browsers never speak gRPC: `/kasse` uses the BFF's HTTP->gRPC gateway
  (DESIGN 4.2), so no gRPC-Web.

### 4.3 BFF + SSE

- Ingress annotations `proxy-buffering: "off"` (ingress-nginx default
  is already off; keep explicit as in BSG `k8s/demo-ui.yaml`),
  `proxy-read-timeout: "3600"`; BFF sends a comment heartbeat every
  15-20 s and `X-Accel-Buffering: no`.
- Azure Standard LB drops idle TCP flows after 4 min by default ->
  `service.beta.kubernetes.io/azure-load-balancer-tcp-idle-timeout: "30"`
  on every LB Service (ingress, MQTT) [A: annotation per cloud-provider-azure].
- Body size: ingress-nginx defaults `client_max_body_size` to 1 MiB;
  multi-modal uploads (photos, audio) to the BFF or the SAM WebUI need
  `proxy-body-size` (SAM's own artifact limit is 100 MB,
  `GATEWAY_ARTIFACT_LIMIT_BYTES`) [V: lab gwe env; lab Ingress and
  controller ConfigMap set no body size]. **This also applies to the
  lab today** -- test a 2 MB image upload in G0.
- The BFF stays single-replica (SSE fan-out in-process), as in BSG.

### 4.4 Gateway API alternative (if ingress-nginx is vetoed)

AKS App Routing with Gateway API (`--enable-gateway-api
--enable-app-routing-istio`, class `approuting-istio`, Istio-managed
Envoy, GA, the successor of the managed NGINX add-on) [V: MS Learn
`app-routing-gateway-api`, updated 2026-11-06]. Supports HTTPRoute
timeouts and GRPCRoute [A: GRPCRoute on the managed CRD channel], no
rate limiting, no snippets. Cost: SAM needs the URL-scheme workaround
from 2.4 and every lab Ingress gets an HTTPRoute twin in the aks
overlay (+1 PT). Keep as a prepared fallback, not the plan.

---

## 5. Sizing, region, security, cost

### 5.1 Workload requests (planning numbers)

| Workload | CPU req | Mem req | Mem limit | Note |
|---|---|---|---|---|
| SAM gwe / awe / str | 0.5 / 1 / 0.5 | 1 / 1.5 / 2 GiB | 2 / 3 / 6 GiB | chart defaults, awe+str raised [V: `CHART/values.yaml`, SAM compute doc] |
| PubSub+ Standard (`prod1k`) | 2 | ~6.5 GiB | = req | [A: Solace sizing calculator]; `dev` size (1 vCPU, ~3.4 GiB, 100 connections) suffices for G0 |
| gpos-pos, loyalty, engine, ui | 4 x 0.1-0.25 | 4 x 256-512 MiB | 4 x 512 MiB-1 GiB | engine renders bitmaps (Pillow) |
| Keycloak 26 | 0.5 | 1 GiB | 1.5 GiB | DB on PG Flexible |
| ingress-nginx (2) | 0.2 | 256 MiB | 512 MiB | |
| cert-manager (3 pods) | 0.1 | 200 MiB | | |
| Prometheus/Grafana/Loki/Alloy | ~0.8 | ~3 GiB | ~4.5 GiB | Prometheus 4Gi limit (lab WAL-spiral lesson) |
| AKS system pods per node | ~0.3-0.5 | ~0.7-1 GiB | | coredns, metrics-server, CSI, konnectivity, Cilium |
| **Sum** | **~7.5-8 vCPU** | **~19-20 GiB** | | |

Node choice: **2 x Standard_D8as_v6** = 16 vCPU / 64 GiB nominal
(matches DESIGN 4.8's 16 vCPU / 64 GB). AKS reserves kubelet memory
proportional to `--max-pods` on current versions -> set `--max-pods
110` and confirm `Allocatable` with `kubectl describe node` [A]. One
node alone cannot hold all CPU *requests* -> give a `demo-critical`
PriorityClass to SAM, broker, gpos, Keycloak, ingress, and a lower one
to monitoring, so a single-node degrade sheds monitoring first.
Pin the pool to **one availability zone**: Azure Disk (LRS) PVs are
zonal and could not re-attach to a node in another zone. No cluster
autoscaler (single-replica stateful pods must not be shuffled).

Disks: OS 128 GiB managed (P10) per node; PVs `managed-csi-premium`:
broker 64 GiB (P6), Prometheus 20 GiB, Loki 20 GiB. RWX is not needed
(SAM `volumes` feature stays off); if it ever is, `azurefile-csi-premium`
(NFS) replaces the lab's hostPath workaround [V: CHART values `volumes`].

### 5.2 Region and latency

- **Germany West Central (Frankfurt)**, 3 AZs; all chosen SKUs priced
  there [V: retail prices API]. Booth (Duesseldorf) -> Frankfurt over
  fixed line ~10-20 ms, over 5G ~30-60 ms [A: G0-18 measures]. "Scan ->
  row < 0.3 s" stays reachable.
- LLM: LiteLLM resolves to AWS addresses (US) [V: dig; region A]; adds
  ~100 ms per call versus a 4.5-5.6 s fast-agent call -- negligible.

### 5.3 Security model

- **Booth access (recommended): WireGuard site-to-site.** A
  `Standard_B2ats_v2` Ubuntu VM in `snet-wg` with a static public IP,
  NSG allowing only UDP 51820 (WireGuard answers nothing to
  unauthenticated packets), IP forwarding + MASQUERADE, so no UDRs are
  needed. Peers: booth router (Teltonika RUTX50, WireGuard in RutOS
  [A]), each developer Mac, the `/op` laptop. Booth-initiated tunnel ->
  dynamic Messe/5G IPs do not matter; reconnects after WAN failover.
  Equivalent to the tunnel already planned in DESIGN 4.8/10.2.
- Fallbacks: (a) public ingress with TLS + IP allowlist (breaks on 5G
  failover unless both WAN IPs are static -> ask GEBIT); (b) Azure VPN
  Gateway S2S IPsec (~EUR 130+/month, slow to deploy) -- not needed.
- Messe network may filter UDP: run WireGuard on UDP 443 if 51820 is
  blocked; ask GEBIT logistics for the uplink's policy and whether the
  IP is static.
- Ingress is **internal only**; public DNS names resolve to private
  IPs (harmless, unreachable outside the tunnel); certificates from
  Let's Encrypt DNS-01, so kiosks need no CA profile and Keycloak/SAM
  trust each other with the system bundle.
- Kubernetes API: public endpoint with **authorized IP ranges**
  (office/home IPs + the WireGuard VM's public IP; booth/admin Macs
  route the API IP through the tunnel), Entra ID login for kubectl;
  break-glass `az aks command invoke` needs no network path. A
  private cluster is not worth the jump-host overhead for a demo.
- Broker: chart default `service.type: LoadBalancer` would publish
  SEMP/SMF/MQTT on a PUBLIC IP -> set `ClusterIP` and expose only MQTT
  1883 on an internal LB; never expose SEMP; replace every `default` /
  `admin` credential of the lab (`AMD/local-k8s-values.yaml:69-71`,
  Keycloak admin/admin, demo users password=username) with values from
  `.env.aks`; keep demo users but give them real passwords.
- PG Flexible VNet-integrated (no public endpoint); seed via an
  in-cluster Job or `kubectl run psql`. Blob: no public access,
  workload identity, no account keys in values.
- Secrets: `.env.aks` (gitignored) -> `--set-string` / `kubectl create
  secret`, as in the lab. Key Vault + CSI driver optional.

### 5.4 Cost (EUR list prices, Germany West Central, excl. VAT)

Unit prices [V: Azure Retail Prices API, 2026-11-10]: D8as_v6 0.3941/h,
D4as_v6 0.1975/h, D8ps_v6 (arm64) 0.3007/h, D8s_v5 0.4129/h; AKS
Standard tier 0.0898/h; PG Flexible B2ms 0.1429/h, B2s 0.0715/h,
GP Ddsv5 2 vCore 0.1903/h, storage 0.123/GB-month; ACR Basic 0.1496/day;
P10 disk 19.46/month, P6 10.08/month; Standard static public IP
0.0045/h; B2ats_v2 0.0097/h.

| Item | EUR / month (24/7) |
|---|---|
| 2 x D8as_v6 nodes | 575 |
| AKS Standard tier (SLA) | 66 |
| 2 x OS disk P10 | 39 |
| PVs (broker P6, monitoring 2 x P6/E) | 20-30 |
| PG Flexible B2ms + 32 GB | 108 |
| ACR Basic | 5 |
| Blob, DNS zone, egress | ~5 |
| Standard LB rules/data [A] + 3 public IPs | ~30 |
| WireGuard VM + disk | ~10-15 |
| **Total** | **~860 (~28/day)** |

- Build-up (Nov-Dec): `az aks stop` nights/weekends cuts nodes to zero
  (PVs kept) -> ~EUR 450-550/month. PG Flexible can be stopped too
  (max 7 days, then auto-start).
- Whole period Nov 2026 - Feb 2027: **~EUR 2.0-3.0k**; fair fortnight
  24/7 ~EUR 430. Optional: PG GP D2ds_v5 for the fair (+~EUR 35/month);
  Free tier during G0/G1 (-EUR 66/month), Standard from G2.
- LLM tokens are separate (LiteLLM key; lab models have pricing null).

---

## 6. Deployment approach

### 6.1 Repository layout (proposal)

```text
gebit-price-agent-demo/
  k8s/
    base/                namespace, configmap, pos, loyalty, engine, ui,
                         Services (grpc ports h2c), NO hosts/issuers
    components/
      ingress/           Ingress objects (BFF, pos-grpc, loyalty-grpc);
                         ssl-redirect annotation + TLS (lab Kyverno compliant)
    overlays/
      lab/               *.solace.lab, solace-lab-ca-issuer, registry.solace.lab,
                         broker tcp://host.docker.internal:55557, PG host
                         host.docker.internal:5432, registry-pull-secret
      aks/               *.<domain>, letsencrypt-dns, <acr>.azurecr.io, broker
                         svc DNS, PG Flexible + sslmode=require, PriorityClass,
                         resources, internal-LB MQTT Service
      gebit-lab/         (DESIGN 4.7)
  infra/aks/
    az-foundation.sh     RG, VNet, AKS, ACR, PG, Blob, DNS, identities,
                         WireGuard VM, maintenance config, budget
    addons.sh            ingress-nginx (values-aks), cert-manager (+WI),
                         ClusterIssuers, pubsubplus, keycloak, monitoring
    sam-values-aks.yaml  overlay on agent-mesh-deployment/local-k8s-values.yaml
    broker/              Terraform root reusing EMD/terraform/modules/{vpn,client,queue}
                         (provider url via kubectl port-forward 8080)
    stop.sh / start.sh   az aks stop/start (+ awe restart after gwe ready)
  mesh/                  unchanged; endpoint placeholders from .env.<target>
  scripts/install.sh     TARGET=solace-lab|aks  k8s|mesh|all  (BSG pattern)
  .env.aks.example       placeholders only
```

Hostnames per overlay as explicit kustomize patches (no partial-string
replacements); secrets from `.env.<target>` via `kubectl create secret
... --dry-run=client -o yaml | kubectl apply -f -` (BSG pattern). SAM
via Helm `-f AMD/local-k8s-values.yaml -f infra/aks/sam-values-aks.yaml`
with `--set-string` secrets. Infra as `az` CLI script (matches the
repo's shell style; Bicep/Terraform-azurerm optional).

### 6.2 Ordered steps (with person-days)

| # | Step | Gate | PT |
|---|---|---|---|
| 1 | Subscription/RG owner, vCPU quota (Dasv6, GWC), domain + delegated Azure DNS zone, budget alert | G0 (by 20.11.) | 0.5 |
| 2 | Foundation script: VNet/subnets, AKS 1.36 (overlay+Cilium, WI, OIDC issuer, ACR attach, 1 AZ, auto-upgrade off, authorized IPs), ACR, PG Flexible 18 (VNet), Storage+container, UAMIs + federated credentials | G0 | 1.5 |
| 3 | Add-ons: ingress-nginx internal LB (health-probe + idle-timeout annotations), cert-manager + LE DNS-01 (staging + prod issuers), PriorityClasses, lean monitoring + SAM dashboards/datasource | G0/G1 | 1.5 |
| 4 | Broker: pubsubplus (ClusterIP, pinned image in ACR, 64Gi premium), Terraform root for VPNs `sam`/`default`, clients, spool quotas; internal LB for MQTT | G1 | 1.0 |
| 5 | Keycloak: port `INFRA/keycloak/manifests` (DB on PG Flexible, LE TLS, `auth.<domain>`), realm, parametrised client/user scripts, kiosk-friendly session lifetimes | G1 | 1.0 |
| 6 | SAM: ACR image load (crane), AKS profile in `agent-mesh-deployment` (env-parametrised scripts, no NodeHosts), Certificate before helm (DNS-01 may need > 120 s), helm install, `provision.sh` incl. `notify:_:send`, health/`/api/v2/platform/health`, metrics | G1 | 2.0 |
| 7 | Images: buildx multi-arch to ACR, lab tag unchanged, kustomize image overrides | G1 | 0.5 |
| 8 | Demo overlays `aks` (+ shared base/components), gRPC Ingresses, SSE/body-size, secrets, `install.sh TARGET=aks`, mesh render with AKS endpoints | G1 | 1.5 |
| 9 | WireGuard gateway VM (cloud-init), peers (RUTX50, Macs, `/op`), DNS records, G0-18 RTT over cable and 5G, L3 switch incl. copy of LE cert secrets to the lab MacBook | G0 spike / G2 | 1.5 |
| 10 | Hardening/ops: maintenance windows excluding 12.-20.02.2027, version freeze, stop/start scripts, preflight `TARGET=aks` (tunnel, broker spool, PG, SAM, LLM probe), PG PITR + disk snapshots before G4 and each fair day, runbook | G2/G4 | 1.5 |
| 11 | Drills: full teardown + rebuild from scratch (LE staging), 24 h soak at 450 runs/h, node-loss drill, L3 fallback drill | G3/G4 | 1.5 |
| | **Total** | | **~14 PT** |

Minimal path (~9-10 PT): everything in-cluster (SAM bundled
persistence on Azure Disk + in-cluster Postgres), Free tier, public
ingress with IP allowlist instead of the tunnel, no rebuild drill.
Not recommended because the 5G failover breaks IP allowlists and the
data would die with the cluster.

Day-to-day: develop and test on the lab (fast arm64 loop), promote to
AKS at the end of every gate with the same `install.sh`, and run the
preflight against both targets.

---

## 7. AKS-specific risks (ranked)

| # | Risk | Mitigation |
|---|---|---|
| R1 | **ingress-nginx is retired upstream**: best-effort maintenance ended March 2026, no further releases or security fixes; the AKS managed NGINX add-on gets critical patches only until Nov 2026 [V: AKS blog 2025-11-13, MS Learn] | do not use the add-on; self-install pinned 1.15.1 on an **internal** LB only (no internet exposure), snippets off; Gateway API overlay (4.4) prepared as fallback; owner decision |
| R2 | SAM chart/lab scripts assume the lab: `registry.solace.lab`, `registry-pull-secret` (chart validation fails if missing), Kyverno CA injection, `solace-lab-ca-issuer`, CoreDNS NodeHosts patch (AKS add-on managed), `host.docker.internal` broker, `sam.solace.lab` in 6 scripts | AKS profile + overlay (2.1, 2.2); keep namespace/release/namespaceId and identities identical |
| R3 | External persistence is a code path the lab never ran (db-init vs Azure admin, TLS default `prefer`, immutable `applicationPassword`, sam-doctor WI label) | G0 spike on AKS: install, provision, run a workflow, restart all pods, verify artifacts in Blob; fallback = bundled persistence on `managed-csi-premium` |
| R4 | Azure LB idle timeout 4 min vs 900 s MCP calls, SSE, MQTT/SMF | `azure-load-balancer-tcp-idle-timeout: "30"` + app heartbeats/keepalives |
| R5 | pubsubplus chart default `LoadBalancer` = public broker incl. SEMP; lab default credentials | `ClusterIP`, internal LB for MQTT only, new passwords |
| R6 | Zonal Azure Disks + single-replica pods; image pull of str (1.6 GB) on a fresh node takes minutes | single-AZ pool, no autoscaler, PriorityClasses, keep nodes stable; optional pre-pull DaemonSet |
| R7 | Ingress body limit 1 MiB vs multi-modal uploads (lab too) | `proxy-body-size` on SAM and BFF Ingresses; test in G0 |
| R8 | Auto-upgrades / node-image updates / planned maintenance during the fair | `--auto-upgrade-channel none`, `--node-os-upgrade-channel None`, maintenance config outside 12.-20.02., freeze after G4 (05.02.2027) |
| R9 | Subscription governance (Azure Policy denying public IPs, private-cluster mandates, tag rules, Defender), vCPU quota, who owns billing and Entra rights for UAMIs/federated credentials | settle in G0 step 1; fallback SKU Dasv5/Dsv5 if Dasv6 capacity fails |
| R10 | Cluster stop/start restarts gwe+awe together -> DB-managed agents may not load | `start.sh` restarts awe after gwe ready, then preflight; no stops during the fair |
| R11 | Let's Encrypt rate limits during rebuild drills; cert renewal timing | staging issuer for drills; force-renew before freeze (90-day certs renew at day 60) |
| R12 | Messe uplink filters UDP / changes IP | WireGuard on UDP 443 if needed, 5G path, public-allowlist fallback; questions to GEBIT logistics |
| R13 | LiteLLM egress: proxy outside EU, possible IP allowlist on the proxy, key exposure | static AKS outbound IP (or NAT gateway) to announce; key only in Secret; LLM probe in preflight |
| R14 | Multi-arch builds under QEMU slow/flaky for native wheels | wheels exist for both arches; fallback `az acr build` |
| R15 | Network policy: awe/str must reach `gpos-engine:8765` across namespaces (lab has none [V: BSG connector notes]) | no NetworkPolicies, or explicit allow if added later |
| R16 | Cost runaway after the fair | budget alert; `az group delete` date in the runbook (or handover to GEBIT) |

L3 fallback note: the Rancher Desktop failure modes (clock wedge,
`vz.pid`, stale IP, dead port forwards) disappear from the main path
but stay relevant for the lab MacBook as L3 (DESIGN 12.1). With
Let's Encrypt hostnames, L3 needs a copy of the current certificate
secrets on the MacBook, otherwise kiosks get certificate errors after
the router DNS switch.

---

## 8. Open decisions for the owner

1. Ingress controller: ingress-nginx (parity, EOL accepted, internal
   only) vs. Gateway API (supported, +1 PT, SAM URL workaround).
   Recommendation: ingress-nginx.
2. SAM persistence on AKS: external (PG Flexible + Blob, recommended)
   vs. bundled (lab parity).
3. IdP: Keycloak in-cluster (recommended) vs. Entra ID.
4. Broker: in-cluster PubSub+ Standard (recommended) vs. Solace Cloud.
5. Booth access: WireGuard to a gateway VM (recommended) vs. public
   ingress with IP allowlist.
6. Node arch: amd64 D8as_v6 (recommended, GEBIT handover) vs. arm64
   Cobalt D8ps_v6 (cheaper, lab image parity).
7. Domain for public DNS/certificates (subdomain delegation from a
   Solace-owned domain or a dedicated demo domain).
8. Azure subscription owner, billing, Entra admin rights, policy
   constraints; when the cluster may be torn down after the fair.

## Sources

- SAM 2.542.1 docs (CLI capture): `samdocs/installing__kubernetes__production.md`,
  `installing__kubernetes__airgap.md`, `installing__kubernetes__compute-resources.md`,
  `installing__before-you-begin.md`, `administering__production-readiness-checklist.md`,
  `administering__tls.md`
- Chart: `CHART/values.yaml`, `values.schema.json:280-300,560-600`,
  `templates/_config_helpers.tpl:10-75`, `templates/_helpers.tpl:185-204`,
  `templates/_validations.tpl:95-210`, `templates/ingress.yaml`,
  `config/gwe/01-s3-init.initContainer.tpl`, `02-db-init.initContainer.tpl`,
  `charts/persistence-layer/values.yaml`
- Repo: `AMD/local-k8s-values.yaml`, `AMD/scripts/start.sh`,
  `AMD/CLAUDE.md`, `AMD/README.md`, `EMD/docker-compose.yaml`,
  `EMD/terraform/*`, `INFRA/*`, `REPO/bsg-trading-desk-demo/{Makefile,k8s,mesh}`,
  `REPO/gebit-price-agent-demo/DESIGN.md` 4.x, 10.x, 12.x
- AKS ingress-nginx update: <https://blog.aks.azure.com/2025/11/13/ingress-nginx-update>
- AKS App Routing Gateway API: <https://learn.microsoft.com/azure/aks/app-routing-gateway-api>
- AKS supported versions: <https://learn.microsoft.com/azure/aks/supported-kubernetes-versions>
- PG 18 on Flexible Server: <https://techcommunity.microsoft.com/blog/adforpostgresql/postgresql-18-now-ga-on-azure-postgres-flexible-server/4469802>
- PubSub+ Helm chart: <https://github.com/SolaceProducts/pubsubplus-kubernetes-helm-quickstart/blob/master/pubsubplus/README.md>
- Azure Retail Prices API (EUR, germanywestcentral): <https://prices.azure.com/api/retail/prices>
