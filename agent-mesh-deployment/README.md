# Agent Mesh Deployment

Helm-based deployment of Solace Agent Mesh (SAM) v2 on Kubernetes.
This deployment connects to the `sam` VPN on `solace-1` created
by the [event-mesh-deployment](../event-mesh-deployment/README.md)
and requires a running Solace Event Mesh as its messaging backbone.

SAM v2 is the Go-based generation of Agent Mesh. Three components
replace the former single core pod:

- **gwe** (Entrypoint Executor) -- serves the WebUI, the platform
  API and all entrypoints on one port; the only component behind
  the ingress.
- **awe** (Agent-Workflow Executor) -- runs agent workflows,
  including the orchestrator.
- **str** (Secure Tool Runtime) -- authenticates and executes
  tool invocations (own image with the Go and Python tool venvs).

There is no separate agent-deployer in v2.

## Prerequisites

### Offline artifacts (SAM delivery package)

The v2 chart and images are distributed as an offline delivery
package and are deliberately not checked in. `.env` points at the
local copies:

- `SAM_CHART_PATH` -- unpacked Helm chart directory
- `SAM_APP_IMAGE_TAR` -- app image tarball (gwe/awe)
- `SAM_STR_IMAGE_TAR` -- str image tarball
- `SAM_CLI_TAR` -- sam CLI tarball (for the RBAC step)

### Cluster Infrastructure (from `solace-lab-infrastructure`)

All four components below must be installed on the target
Kubernetes cluster before deploying SAM. They are provided by
the companion repository
[`solace-lab-infrastructure`](https://github.com/martensa/solace-lab-infrastructure):

- **NGINX Ingress Controller** -- `ingress/`
- **PKI** -- `pki/`
  - cert-manager with ClusterIssuer `solace-lab-ca-issuer`
  - trust-manager bundle `solace-lab-ca-trust-bundle`
  - Kyverno policy `inject-solace-lab-ca-trust-bundle`
    (mounts the CA bundle at
    `/etc/ssl/certs/ca-certificates.crt` AND sets
    `SSL_CERT_FILE` + `REQUESTS_CA_BUNDLE` env vars)
  - Kyverno policy `inject-registry-pull-secret`
- **Private Registry** -- `registry/`
  - Available at `https://registry.solace.lab`
  - Holds the SAM app and str images
    (loaded by `scripts/load-images.sh`)
- **Keycloak** -- `keycloak/`
  - OIDC provider at `https://auth.solace.lab` with the
    `solace-lab` realm

Additionally, the `start.sh` in this deployment registers
`sam.solace.lab` in CoreDNS NodeHosts -- SAM makes internal
self-calls to its own external URL during the OAuth flow, which
requires cluster-internal hostname resolution.

### Additional Services

- **Solace Event Mesh** running locally
  (see [`../event-mesh-deployment/`](../event-mesh-deployment/))
  with the `sam` VPN on `solace-1`
- **LLM Service** endpoint (e.g. a LiteLLM proxy) with an API key
- **Demo data stores** (only when a demo is installed): each
  demo's `install.sh` starts its own host data stores -- the
  standalone postgres container (`postgres` + `pgadmin`, managed
  outside this repo, reached via `host.docker.internal:5432`)
  and a demo-specific MongoDB. See the demo directories
  (`../sam-retail-ops-demo/`, `../sam-manufacturing-ops-demo/`).

### Local CLI Tools

- `kubectl` configured for your cluster
- `helm` 3
- `docker` (for the image load step)
- `bash`, `curl`, `jq`, `python3`
- the `sam` CLI from the delivery package (see below)

### Installing the sam CLI

The CLI ships in the delivery package as
`solace-agent-mesh-<version>-cli-<os>-<arch>.tar.gz` (a single
static binary). Install it for interactive use (`sam auth login`,
`sam config`, `sam api`):

```bash
mkdir -p ~/.local/bin
tar -xzf ~/Downloads/solace-agent-mesh-<ver>-cli-darwin-arm64.tar.gz \
  -C ~/.local/bin sam
sam --help   # verify
```

Notes:

- `~/.local/bin` must come early in the PATH -- in particular
  BEFORE any Python framework bin directory if the old v1 Python
  CLI (`pip install solace-agent-mesh`, also named `sam`) is
  still installed; the v2 Go CLI must win the lookup.
- The repo scripts do not require this install: they resolve the
  CLI via `scripts/lib/common.sh` (`SAM_CLI_PATH` from `.env`,
  then PATH, then auto-extract from `SAM_CLI_TAR`). The install
  is for the interactive login and ad-hoc `sam` commands.

## Architecture Overview

```text
+---------------------+
|   Keycloak (OIDC)   |
+----------+----------+
           |
+----------+----------+     +------------------+
| Solace Agent Mesh   |     |   LLM Service    |
| gwe + awe + str     +---->| (LiteLLM Proxy)  |
| (sam.solace.lab)    |     +------------------+
+----------+----------+
           |
           | ws://host.docker.internal:8008
           |
+----------+----------+
|  solace-1 / VPN sam |
|  (Event Mesh)       |
+---------------------+
```

SAM connects to the `sam` Message VPN on `solace-1` via WebSocket
(`global.broker.embedded: false` -- the chart's embedded broker is
not used). The broker provides the messaging backbone for
agent-to-agent communication, task routing, and event
distribution. `global.persistence.namespaceId` (kept at
`sam-solace-lab`) namespaces the broker topics.

Bundled persistence (PostgreSQL + SeaweedFS from the
`persistence-layer` subchart) provides the datastores; both images
are public on Docker Hub and are not mirrored into the private
registry.

## Quick Start

### 1. Prepare credentials and artifact paths

```bash
cp .env.example .env
```

Edit `.env` and set `LLM_SERVICE_API_KEY` plus the four offline
artifact paths (`SAM_CHART_PATH`, `SAM_APP_IMAGE_TAR`,
`SAM_STR_IMAGE_TAR`, `SAM_CLI_TAR`). The Keycloak client secret is
populated in the next step.

### 2. Create the Keycloak OIDC client

```bash
./scripts/setup-keycloak-client.sh
```

This creates a confidential OIDC client `solace-agent-mesh`
in the `solace-lab` realm and adds a group membership mapper so
the `groups` claim is included in tokens (required for SAM RBAC).
Copy the printed client secret into `.env` as
`KEYCLOAK_CLIENT_SECRET`.

### 3. Create Keycloak groups and demo users

```bash
./scripts/setup-keycloak-users.sh
```

This creates five groups (`admin`, `user`, `viewer`,
`data_engineer`, `power_user`) and five demo users with password
equal to the username. `sam_admin` (group `admin`) is the
bootstrap admin seeded via the Helm values.

### 4. Load the SAM images into the private registry

```bash
docker login registry.solace.lab   # once
./scripts/load-images.sh
```

Loads the offline image tarballs into Docker, retags them for
`registry.solace.lab` and pushes them.

### 5. Deploy

```bash
./scripts/start.sh
```

The script performs the following steps:

1. Checks that `kubectl`, `helm`, `jq` are available
2. Validates `.env` (secrets plus `SAM_CHART_PATH`)
3. Creates the Kubernetes namespace
4. Provisions the `sam-tls` certificate via cert-manager and
   waits for it (the chart validates its existence at install)
5. Registers `sam.solace.lab` in CoreDNS NodeHosts
6. Runs `helm upgrade --install` from the local chart directory
   with the values file, injecting secrets via `--set`
7. Waits for pods and prints the release status

The chart's `sam-doctor` pre-install hook checks broker, LLM and
OIDC reachability; it is configured warn-only
(`samDoctor.failOnError: false`) so a briefly unavailable
dependency does not block the push-button flow.

### 6. Apply RBAC (roles + group mappings)

```bash
./scripts/rbac/apply-rbac.sh
```

In v2, only bootstrap admins are seeded via Helm values; roles,
Keycloak group claim mappings and default roles are DB-managed
and applied post-install with `sam config apply`. See
[`scripts/rbac/README.md`](scripts/rbac/README.md). The first run
needs a browser login as `sam_admin`:

```bash
sam auth login solace-lab --url https://sam.solace.lab
```

### 7. Models: output limit and additional LLMs

```bash
cd scripts/models && ./set-max-tokens.sh
```

Sets `modelParams.max_tokens` (default 16384) on the `general`
model and restarts the agents. Without it the chart-seeded empty
`modelParams` reintroduce the tool-call truncation failure
documented in [`scripts/models/README.md`](scripts/models/README.md).
Repeat with `--model-alias planning` and `--model-alias report_gen`.

`start.sh` additionally applies five extra model aliases
(`workflow`, `reasoning`, `coding`, `expert`, `fast`) from the
declarative package in `scripts/models/` and probes every model
upstream. Standalone runs:

```bash
cd scripts/models && ./apply-models.sh
```

```bash
cd scripts/models && ./apply-models.sh --probe-only
```

Note: the platform normalizes model aliases to lowercase on
create, so all aliases are lowercase by design.

### 8. Platform entrypoints (developer-mcp)

`start.sh` also applies the `developer-mcp` MCP entrypoint from
the declarative package in `scripts/entrypoints/` -- it exposes
the mesh agents as MCP tools at `https://sam.solace.lab/gw/dev/`
for developer clients (Claude Code, MCP Inspector, the SAM
desktop app). Standalone runs:

```bash
cd scripts/entrypoints && ./apply-entrypoints.sh
```

```bash
cd scripts/entrypoints && ./apply-entrypoints.sh --probe-only
```

See [`scripts/entrypoints/README.md`](scripts/entrypoints/README.md)
for the MCP tool naming and the Claude Code connection guide.

### 9. Install a demo

The platform itself carries NO demo content. Demos are layered
on top as self-contained packages with their own core (domain
connectors, schema skills, query experts), overlay (event-driven
workflows, entrypoints), eval package and dashboard:

```bash
cd ../sam-retail-ops-demo && ./install.sh
```

```bash
cd ../sam-manufacturing-ops-demo && ./install.sh
```

Both are idempotent; the matching `uninstall.sh` removes the
demo again (`--keep-core` keeps the demo's core agents for fast
overlay switching). Requires the `sam auth login` from step 6.

### 10. Teardown

```bash
./scripts/stop.sh
```

This uninstalls the Helm release, deletes PVCs, removes the
namespace, removes `sam.solace.lab` from CoreDNS NodeHosts,
removes the Keycloak users and groups, and deletes the Keycloak
OIDC client.

## Rebuilding after teardown

`stop.sh` destroys the platform database, and with it ALL
DB-managed content: RBAC roles, claim mappings and default roles,
the developer-mcp entrypoint, any installed demo (core + overlay)
and the model `max_tokens` tuning. The Keycloak client is deleted
too, so the sam CLI login cache is invalid. To rebuild:

1. `./scripts/setup-keycloak-client.sh` -- paste the NEW client
   secret into `.env`
2. `./scripts/setup-keycloak-users.sh`
3. `./scripts/start.sh` (`docker login` + `load-images.sh` are
   only needed if the private registry itself was rebuilt --
   images persist outside the namespace)
4. `sam auth login solace-lab --url https://sam.solace.lab`
   (as `sam_admin`)
5. `./scripts/rbac/apply-rbac.sh`
6. `cd scripts/models && ./set-max-tokens.sh` (plus
   `--model-alias planning` and `--model-alias report_gen`),
   then `./apply-models.sh` and
   `cd ../entrypoints && ./apply-entrypoints.sh` -- during the
   rebuild, `start.sh` ran before the `sam auth login` existed,
   so both post-install hooks were skipped with a warning
7. Reinstall the demo, e.g.
   `cd ../sam-retail-ops-demo && ./install.sh` (starts the demo
   data stores and re-creates core, overlay, eval package and
   dashboard, including the model bindings)
8. If the desktop app is connected:
   `cd scripts/desktop && ./generate-manifest.sh && ./connect.sh`
   (the MCP tool names embed platform-DB UUIDs, which the rebuild
   changed)

## Observability

SAM is fully wired into the lab's Grafana stack
(`https://monitoring.solace.lab`, folder "SAM": Operations,
Token und Cost, Governance und Security):

- **Metrics**: the SAM configs are baked into the images, so
  `scripts/observability/` overlays them (full-file ConfigMap
  overlays adding a `management_server` block) through a Helm 4
  post-renderer plugin (`sam-observability`, installed by
  start.sh). `/metrics` rides the existing health ports (gwe
  9090, awe/str 8090); `manifests/observability/` adds metrics
  Services + ServiceMonitors. Prometheus picks them up without
  further wiring. Key metrics: `sam_entrypoint_*` (request rate
  and latency), `sam_operation_duration_seconds` (agent/tool),
  `sam_gen_ai_tokens_used_total` and `sam_gen_ai_cost_total`
  (by model), plus `sam_instance_up` and
  `sam_broker_connection_state` health gauges.
- **Logs + audit (governance)**: pod stdout ships via the Alloy
  DaemonSet (infra repo) to Loki. The SAM audit stream
  (`logger_name=audit`) carries userID, agentName, tool,
  duration_ms and RBAC denies -- the "who uses what" view. RBAC
  GRANTS log at DEBUG and are invisible at the default INFO
  level.
- **Traces**: SAM emits no OTel spans in 2.225.14. A2A traffic
  (gwe/awe/str, guaranteed messaging on the `sam` VPN) is traced
  by the BROKER via a telemetry profile and lands in Tempo
  through the event-mesh OTel Collector
  (`sam-solace-lab/a2a/v1/...` spans).
- **Token chargeback per user**: Grafana datasource
  `SAM Platform DB` (read-only role `grafana_ro`) queries the
  `tasks` table (`user_id`, `total_input/output_tokens`,
  `token_usage_details` with per-model breakdown).
- **Platform DB for governance dashboards**: a second datasource
  `SAM Platform Config DB` (uid `sam-platform-config-db`,
  `manifests/observability/grafana-datasource-sam-platform-config.yaml`,
  a ConfigMap in ns `monitoring` where the datasource sidecar
  watches) reads `sam-solace-lab_platform` (agents, RBAC roles and
  claim mappings, model aliases, eval runs). `grafana_ro` has no
  SELECT there by default: `scripts/observability/`
  `grant-grafana-platform-db.sh` grants it idempotently (incl.
  default privileges for future tables), applies the ConfigMap and
  verifies via `has_table_privilege`. The demo install scripts
  call it; stop.sh drops the DB and with it the grant.

Operational notes (learned the hard way):

- **Config drift guard**: the overlays replace image-baked
  configs in full. start.sh diffs them against the delivery
  images (`scripts/observability/check-config-drift.sh`) and
  aborts with re-basing instructions when a new SAM delivery
  changes them.
- The `management_server` block is only honored in the MAIN
  component config; extra `--config` files are rejected
  (`expected YAML list`). Its `port:` is overridden by
  `--health-addr`.
- After a simultaneous gwe+awe restart the DB-managed agents may
  not load (deploy handshake race): restart awe once more AFTER
  gwe is ready.
- Enabling a telemetry profile on a running broker requires a
  BROKER RESTART before spans are generated.
- Keep an eye on the `sam` VPN spool: the gateway viz queue
  (`q/gdk/viz/...`, quota capped to 1 GB) has no consumer and
  fills over time; a full VPN spool (10 GB) blocks ALL task
  publishing ("Spool Over Quota").

## Upgrade

A new SAM delivery changes the Helm chart, the gwe/str images and
the image-baked component configs at the same time, so an upgrade
is a clean rebuild rather than a rolling `helm upgrade`. The
platform database is dropped with the namespace, so every
DB-managed object is re-provisioned afterwards -- the order is in
"Rebuilding after teardown".

Have the new delivery package unpacked (or at least the chart
tarball and the image tarballs to hand) and a `sam` CLI of the
matching version on the PATH before starting.

### 1. Review the new chart (no cluster changes)

```bash
./scripts/upgrade-preflight.sh --new "/path/to/SAM Enterprise Update <ver>"
```

`--new` takes the delivery package directory -- the chart is found
in a subfolder such as `Charts/`, three levels deep at most -- or a
packaged chart (`.tgz`), or an unpacked chart directory. Archives
are classified by content, so the image tarballs in `Images/` are
not mistaken for charts. `--old` defaults to `SAM_CHART_PATH` from
`.env`, i.e. the chart currently deployed.

Delivery package directories are routinely named with spaces, and
sometimes with a trailing one or a non-breaking space that no
terminal shows. When the given path does not exist but exactly one
entry beside it matches once whitespace and punctuation are
ignored, that entry is used and the substitution is reported; with
two candidates it refuses and lists them.

The report answers the questions an upgrade raises:

- Does `local-k8s-values.yaml` still fit? The values schema is
  `additionalProperties: false`, so a key the new chart renamed or
  removed fails the install. Section 3 lists any such key, section
  4 the full schema diff (marking the removed keys this deployment
  sets), and section 7 runs `helm lint` plus `helm template` with
  the real values file.
- Which tags belong in the pins? Section 2 prints the image
  defaults of the new chart -- the gwe, str, s3Init, dbInit,
  postgresql and seaweedfs versions the delivery expects. Section
  5 flags chart defaults that changed underneath an override
  (e.g. the seaweedfs tag), where an override may have become
  redundant or newly wrong.
- What goes into `.env`? Section 6 lists the image and CLI
  tarballs found in the package as ready-to-paste
  `SAM_APP_IMAGE_TAR` / `SAM_STR_IMAGE_TAR` / `SAM_CLI_TAR`
  assignments.

Fix `local-k8s-values.yaml` until sections 3 and 7 are clean.

### 2. Tear the old deployment down

```bash
./scripts/stop.sh
```

This removes the Helm release, the namespace with its PVCs and
released PVs, the observability objects in the `monitoring`
namespace, the `sam-observability` Helm plugin, the CoreDNS
NodeHosts entry, the cached and now version-mismatched `sam` CLI
plus its login cache, and the Keycloak client, groups and users.
Nothing of the old version is left in the cluster.

### 3. Repoint and re-pin

- `.env`: `SAM_CHART_PATH`, `SAM_APP_IMAGE_TAR`,
  `SAM_STR_IMAGE_TAR`, `SAM_CLI_TAR` to the new package --
  preflight section 6 prints the three tarball paths as
  ready-to-paste, already quoted assignments. `.env` is sourced,
  so a path containing a space MUST stay quoted or the variable
  ends up empty. `SAM_CHART_PATH` must be an UNPACKED chart
  directory (`start.sh` checks for `Chart.yaml` in it), so unpack
  the packaged chart once and point it there -- ideally somewhere
  without spaces in the path.
- `local-k8s-values.yaml`: `samDeployment.gwe.image.tag` and
  `samDeployment.str.image.tag` to the versions from preflight
  section 2, plus any values change preflight asked for.
  `scripts/load-images.sh` and `scripts/purge-images.sh` read
  their tags from this file, so there is nothing else to keep in
  sync.

The Keycloak client secret changes with step 2, so re-create the
client and paste the new secret into `.env`:

```bash
./scripts/setup-keycloak-client.sh
./scripts/setup-keycloak-users.sh
```

### 4. Load the new images and re-base the config overlays

```bash
./scripts/load-images.sh
```

`scripts/observability/` replaces three component configs in
full, so a delivery that changed them would be silently overridden
by the stale copies. `start.sh` refuses to deploy on drift; check
and re-base up front, now that the new images are local:

```bash
./scripts/observability/check-config-drift.sh \
  solace-agent-mesh:<app-ver> solace-agent-mesh-str:<str-ver>
```

On drift, refresh each reported base from the new image, review
the vendor diff, and keep the `management_server` block out of it
(it is re-appended from `kustomize/configs/management_server.yaml`):

```bash
docker run --rm --entrypoint cat solace-agent-mesh:<app-ver> \
  /etc/sam/configs/gwe/gwe.yaml \
  > scripts/observability/kustomize/configs/gwe.yaml.base
```

The three bases are `gwe.yaml.base` (`/etc/sam/configs/gwe/gwe.yaml`
in the app image), `awe-sam.yaml.base`
(`/etc/sam/configs/awe/sam.yaml`, app image) and `str.yaml.base`
(`/etc/sam/configs/str/str.yaml`, str image).

### 5. Install and re-provision

```bash
./scripts/start.sh
sam auth login solace-lab --url https://sam.solace.lab
./scripts/rbac/apply-rbac.sh
(cd scripts/models && ./set-max-tokens.sh)
./scripts/models/apply-models.sh
./scripts/entrypoints/apply-entrypoints.sh
```

`start.sh` runs the models and entrypoints hooks itself, but at
that point the `sam` login does not exist yet, so both warn and
are re-run here. Steps 4 onwards of "Rebuilding after teardown"
apply unchanged -- including the demo installs, which are yours to
run afterwards.

### 6. Drop the old images

The old gwe/str images stay in the local Docker daemon and in
`registry.solace.lab` (several GB per version), both outside the
deleted namespace. Once the new version is up and verified:

```bash
./scripts/purge-images.sh --dry-run   # review
./scripts/purge-images.sh             # remove
```

It keeps exactly the tags `local-k8s-values.yaml` pins and drops
every other tag of the SAM repositories, so it stays correct
across upgrades. `./scripts/stop.sh --purge-images` does the same
inline, which is right for abandoning a version but not for an
upgrade: the old images are the fallback until the new ones are
proven. Registry deletion needs the registry to run with
`REGISTRY_STORAGE_DELETE_ENABLED=true`; the script reports it
rather than failing when it does not.

To inspect current values:

```bash
helm get values agent-mesh -n sam-solace-lab
```

## Configuration

### Environment variables (via .env)

Passed to Helm via `--set` at deploy time:

- `KEYCLOAK_ISSUER` -> `sam.oauthProvider.oidc.issuer`
- `KEYCLOAK_CLIENT_ID` -> `sam.oauthProvider.oidc.clientId`
- `KEYCLOAK_CLIENT_SECRET` -> `sam.oauthProvider.oidc.clientSecret`
- `LLM_SERVICE_API_KEY` -> `llmService.llmServiceApiKey`

Consumed by the scripts only (never passed to Helm):

- `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_ADMIN_USER`,
  `KEYCLOAK_ADMIN_PASSWORD` -- Keycloak setup/teardown
- `SAM_CHART_PATH` -- offline chart directory (start.sh)
- `SAM_APP_IMAGE_TAR`, `SAM_STR_IMAGE_TAR` -- image tarballs
  (load-images.sh)
- `SAM_CLI_TAR` / `SAM_CLI_PATH` -- sam CLI (rbac/apply-rbac.sh,
  models/*, entrypoints/apply-entrypoints.sh and the demo
  install/uninstall scripts, via scripts/lib/)
- `RETAIL_DB_USERNAME` / `RETAIL_DB_PASSWORD` (and the `MFG_DB_*`
  pair) -- demo connector credentials (optional; the demo core
  manifests default to postgres/postgres; the demo install
  scripts source this `.env`, so overrides set here apply)

### Helm Values (local-k8s-values.yaml)

All non-sensitive configuration plus demo-only defaults are
defined in `local-k8s-values.yaml`. Key sections:

- **sam** -- authorization, DNS name, session key, OIDC provider
  structure, bootstrap admin, CORS
- **broker** -- external Solace broker connection
  (`ws://host.docker.internal:8008`, VPN `sam`; the embedded
  broker is disabled via `global.broker.embedded: false`)
- **llmService** -- LLM model selection and endpoint (seeded into
  the platform's model configurations at startup)
- **ingress** -- NGINX ingress host (`sam.solace.lab`) with TLS
  via cert-manager; backend is the gwe service
- **global** -- empty `imageRegistry` (the chart default
  `gcr.io/gcp-maas-prod` would be prepended to every image),
  pull secret, external broker toggle, bundled persistence with
  `namespaceId: sam-solace-lab`
- **samDeployment** -- gwe and str images from
  `registry.solace.lab` (awe inherits the gwe image), seaweedfs
  init tag pin
- **persistence-layer** -- seaweedfs tag pin `3.97` (the chart
  default `3.97-compliant` is a Solace-private tag absent from
  Docker Hub)

### CA Trust

No explicit `REQUESTS_CA_BUNDLE` / `SSL_CERT_FILE` values are
set. The Kyverno policy `inject-solace-lab-ca-trust-bundle`
mounts the trust bundle and sets both environment variables in
every SAM pod automatically. The chart's own
`samDeployment.customCA` mechanism is deliberately NOT enabled --
it would mount over the same path.

### Broker Connection

SAM connects to the `sam` VPN on `solace-1` from the
event-mesh-deployment:

- URL: `ws://host.docker.internal:8008`
- VPN: `sam`
- Username: `default`
- Password: `default`

### RBAC

The v2 chart seeds exactly one YAML role (`sam_admin`) and the
bootstrap admin `sam_admin@solace.lab`
(`sam.authenticationRbac.users`). All other roles and the
Keycloak group mappings are DB-managed and live in
[`scripts/rbac/`](scripts/rbac/README.md):

- Roles `sam_user`, `viewer`, `data_engineer`, `power_user`
  (v2 scope grammar `<category>:<resource>:<verb>`)
- Claim mappings for the Keycloak groups `user`, `viewer`,
  `data_engineer`, `power_user` (claim key `groups`)
- Default roles `[sam_user]` for authenticated users without a
  matching group

The Keycloak `admin` group has no claim mapping: mappings may only
reference DB-managed roles, so the admin grant is the Helm-seeded
bootstrap user instead.

## Directory Structure

```text
agent-mesh-deployment/
  .env.example                    Credentials + artifact paths
  .gitignore                      Ignores .env, CLI cache
  local-k8s-values.yaml           Helm values (no secrets)
  manifests/
    sam-tls-certificate.yaml      cert-manager Certificate
  scripts/
    setup-keycloak-client.sh      Create OIDC client
    teardown-keycloak-client.sh   Delete OIDC client
    setup-keycloak-users.sh       Create groups + demo users
    teardown-keycloak-users.sh    Delete groups + demo users
    load-images.sh                Load offline images -> registry
    purge-images.sh               Drop unpinned SAM images
                                  (local daemon + registry)
    upgrade-preflight.sh          Compare a new delivery chart
                                  with the deployed one
    start.sh                      Deploy SAM (local chart path)
    stop.sh                       Full teardown
    lib/                          Shared helpers (sam CLI, .env)
    rbac/                         Declarative RBAC (sam config)
    entrypoints/                  Platform developer-mcp MCP
                                  entrypoint (declarative, v2)
    models/                       Model tuning via sam CLI (v2)
    desktop/                      Connect the SAM desktop app to
                                  this deployment (MCP connector)
  CLAUDE.md                       Claude Code instructions
  README.md                       This file
```

## Demo-only Values -- not for production

- `sam.sessionSecretKey` -- checked-in static value. Rotate per
  environment for production.
- `broker.password: "default"` -- matches the demo broker from
  `../event-mesh-deployment/`.
- `global.persistence.enabled: true` -- bundled PostgreSQL and
  SeaweedFS; DB passwords are derived from the namespaceId. Use
  external managed persistence for production.
- `samDoctor.failOnError: false` -- production installs should
  fail on doctor errors instead of warning.
- Keycloak admin credentials (`admin/admin`) and demo users with
  password equal to username.
- Default LLM endpoint points at an internal Solace LiteLLM
  proxy.

## Accessing SAM

Once deployed, SAM is available at:

- Frontend: `https://sam.solace.lab`
- Platform API: `https://sam.solace.lab/api/v1/platform`

Ensure your DNS or `/etc/hosts` points `sam.solace.lab` to
your ingress controller IP.

## References

- SAM v2 documentation (docs.solace.com):
  <https://docs.solace.com/Agent-Mesh/Framework/get-started/agent-mesh-overview.htm>
- RBAC reference (scope grammar, kinds):
  <https://docs.solace.com/Agent-Mesh/Framework/reference/rbac-reference.htm>
- Enabling SSO:
  <https://docs.solace.com/Agent-Mesh/Framework/administering/enabling-sso.htm>
- Declarative configuration (`sam config`):
  <https://docs.solace.com/Agent-Mesh/Framework/building/declarative-config/configuration-kinds.htm>
- CLI reference:
  <https://docs.solace.com/Agent-Mesh/Framework/reference/cli.htm>
- Helm values reference:
  <https://docs.solace.com/Agent-Mesh/Framework/reference/helm-values.htm>
