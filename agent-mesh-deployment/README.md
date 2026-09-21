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
- `SAM_CLI_PATH` or `SAM_CLI_TAR` -- the sam CLI (an installed
  binary, or the CLI tarball when the package ships one;
  2.348.22 does not)

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
  and a demo-specific MongoDB (insurance adds Qdrant plus an MCP
  server on port 8765). See the demo directories
  (`../sam-retail-ops-demo/`, `../sam-manufacturing-ops-demo/`,
  `../sam-insurance-ops-demo/`).

### Local CLI Tools

- `kubectl` configured for your cluster
- `helm` 3
- `docker` (for the image load step)
- `bash`, `curl`, `jq`, `python3`
- the `sam` CLI from the delivery package (see below)

### Installing the sam CLI

The CLI is a single static binary. Some delivery packages ship it
as `solace-agent-mesh-<version>-cli-<os>-<arch>.tar.gz`; others do
not (2.348.22 has only `Charts/` and `Images/`) -- then get the
matching CLI separately. Install it for interactive use
(`sam auth login`, `sam config`, `sam api`) and for the scripts:

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
- The repo scripts resolve the CLI via `scripts/lib/common.sh`:
  `SAM_CLI_PATH` from `.env`, then PATH, then auto-extract from
  `SAM_CLI_TAR`. Only a package that ships the CLI tarball can
  rely on that last fallback; otherwise the install above (or
  `SAM_CLI_PATH`) is required. Keep `SAM_CLI_PATH` on the current
  version -- it wins over the PATH.

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

Edit `.env` and set `LLM_SERVICE_API_KEY`,
`GOOGLE_AI_STUDIO_API_KEY` (the `google gemini` model alias) and
the offline artifact paths (`SAM_CHART_PATH`, `SAM_APP_IMAGE_TAR`,
`SAM_STR_IMAGE_TAR`, plus `SAM_CLI_PATH` or `SAM_CLI_TAR`). The
Keycloak client secret is filled in by the next step.

### 2. Create the Keycloak OIDC client

```bash
./scripts/setup-keycloak-client.sh
```

This creates a confidential OIDC client `solace-agent-mesh`
in the `solace-lab` realm and adds a group membership mapper so
the `groups` claim is included in tokens (required for SAM RBAC).
The script writes the client secret into `.env`
(`KEYCLOAK_CLIENT_SECRET`) itself; re-running it against an
existing client re-syncs `.env` with the current secret.

### 3. Create Keycloak groups and demo users

```bash
./scripts/setup-keycloak-users.sh
```

This creates six groups (`admin`, `user`, `viewer`,
`data_engineer`, `power_user`, `sam_manager`) and six demo users
with password equal to the username. `sam_admin` (group `admin`)
is the bootstrap admin seeded via the Helm values; `sam_manager`
administers everything in SAM except RBAC (see "RBAC" below).

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
3. Checks that the pinned images still honour the metrics switch
   (`scripts/observability/check-metrics-gate.sh`, warn-only)
4. Creates the Kubernetes namespace
5. Provisions the `sam-tls` certificate via cert-manager and
   waits for it (the chart validates its existence at install)
6. Registers `sam.solace.lab` in CoreDNS NodeHosts
7. Runs `helm upgrade --install` from the local chart directory
   with the values file, injecting secrets via `--set`
8. Waits for pods and prints the release status
9. Provisions the platform content (next step) -- in a terminal
   it opens the browser for the `sam` CLI login first

The chart's `sam-doctor` pre-install hook checks broker, LLM and
OIDC reachability; it is configured warn-only
(`samDoctor.failOnError: false`) so a briefly unavailable
dependency does not block the push-button flow.

### 6. Provision the platform content

The platform database starts empty after every install. Everything
this deployment owns there is re-created by one idempotent script:

```bash
./scripts/provision.sh --login
```

`start.sh` runs it on its own when it runs in a terminal. All steps
go through the `sam` CLI, which needs a browser login as the
bootstrap admin `sam_admin` -- possible only once the platform is
up, which is why this comes after the deploy. `--login` opens that
login when no login cache exists; without it the script expects
an existing login:

```bash
sam auth login solace-lab --url https://sam.solace.lab
```

It runs, in this order (each script also works standalone):

1. `scripts/rbac/apply-rbac.sh` -- roles, Keycloak claim mappings
   and default roles
2. `scripts/models/apply-models.sh` -- the extra model aliases,
   plus a live probe of every upstream
3. `scripts/models/set-max-tokens.sh` -- `max_tokens` on the
   seeded aliases
4. `scripts/entrypoints/apply-entrypoints.sh` -- the
   `developer-mcp` MCP entrypoint

RBAC runs first because it doubles as the login smoke test: a bad
login stops there instead of failing four times.

#### RBAC (roles + group mappings)

In v2, only bootstrap admins are seeded via Helm values; roles,
Keycloak group claim mappings and default roles are DB-managed
and applied post-install with `sam config apply`. See
[`scripts/rbac/README.md`](scripts/rbac/README.md).

#### Models: output limit and additional LLMs

`set-max-tokens.sh` sets `modelParams.max_tokens` (default 16384)
on the chart-seeded `general`, `planning` and `report_gen`
aliases, skips an alias that is already there, and restarts the
agents once if anything changed. Without it the chart-seeded empty
`modelParams` reintroduce the tool-call truncation failure
documented in [`scripts/models/README.md`](scripts/models/README.md).
`--model-alias <alias>` tunes a single alias.

`apply-models.sh` applies six extra aliases from the declarative
package in `scripts/models/` -- `workflow`, `reasoning`, `coding`,
`expert`, `fast` through the LiteLLM proxy, and `google gemini`
directly on the Gemini API (own key, `GOOGLE_AI_STUDIO_API_KEY`) --
and probes every model upstream. Probe only:

```bash
cd scripts/models && ./apply-models.sh --probe-only
```

Note: the platform normalizes model aliases to lowercase on
create, so all aliases are lowercase by design.

#### Platform entrypoints (developer-mcp)

The `developer-mcp` MCP entrypoint from the declarative package in
`scripts/entrypoints/` exposes the mesh agents as MCP tools at
`https://sam.solace.lab/gw/dev/` for developer clients (Claude
Code, MCP Inspector, the SAM desktop app). Probe only:

```bash
cd scripts/entrypoints && ./apply-entrypoints.sh --probe-only
```

See [`scripts/entrypoints/README.md`](scripts/entrypoints/README.md)
for the MCP tool naming and the Claude Code connection guide.

### 7. Install a demo

The platform itself carries NO demo content. Demos are layered
on top as self-contained packages with their own core (domain
connectors, schema skills, query experts), overlay (event-driven
workflows, entrypoints), eval package and dashboard. Run the
commands from this directory (`agent-mesh-deployment/`); the
subshell keeps you here for the next command:

```bash
(cd ../sam-retail-ops-demo && ./install.sh)
```

```bash
(cd ../sam-manufacturing-ops-demo && ./install.sh)
```

```bash
(cd ../sam-insurance-ops-demo && ./install.sh)              # triage (default)
(cd ../sam-insurance-ops-demo && ./install.sh --extended)   # 15-min original
```

- Retail -- "Acme Retail": order events, the incident workflow,
  CRM/OMS/PDM query experts, the POSLOG connector (the POS
  analyst agent is built live in the Builder; `--with-pos` keeps
  a prebuilt one) ([README](../sam-retail-ops-demo/README.md)).
- Manufacturing -- plant events, quality-incident and
  replenishment workflows
  ([README](../sam-manufacturing-ops-demo/README.md)).
- Insurance -- "Acme Insurance": by default the claim triage
  governance demo (one FNOL event -> one decision in ~30 s, with
  an external v1 intake agent); `--extended` installs the 15-min
  event-driven claims operations original instead. Both profiles
  subscribe to overlapping FNOL topics, so switching removes the
  other profile's entrypoint
  ([README](../sam-insurance-ops-demo/README.md)).

Only ONE demo runs at a time (shared host data stores, one MongoDB
on port 27017): each `install.sh` refuses to install over another
demo's overlay. All are idempotent; the matching `uninstall.sh`
removes the demo again (`--keep-core` keeps the demo's core agents
for fast overlay switching, `--dry-run` shows what it would
remove). Each demo also has a `preflight.sh` for the day of the
talk. Requires the `sam auth login` from step 6.

### 8. Teardown

```bash
./scripts/stop.sh
```

Run from `agent-mesh-deployment/`. Uninstall a demo first if one
is installed: `uninstall.sh` needs the running platform, and
`stop.sh` leaves the demo's host data stores and the insurance
external agent (namespace `sam-solace-lab-agents`) in place. It
uninstalls the Helm release, deletes
the PVCs and the namespace, drops the SAM queues on the broker VPN,
removes the observability objects in `monitoring`, removes
`sam.solace.lab` from CoreDNS NodeHosts, the Keycloak users,
groups and OIDC client, and the local `sam` CLI caches.

## Rebuilding after teardown

`stop.sh` destroys the platform database, and with it ALL
DB-managed content: RBAC roles, claim mappings and default roles,
the model aliases and `max_tokens` tuning, the developer-mcp
entrypoint and any installed demo (core + overlay). The Keycloak
client is deleted too, and with it the `sam` CLI login cache. To
rebuild:

1. `./scripts/setup-keycloak-client.sh` -- writes the NEW client
   secret into `.env`
2. `./scripts/setup-keycloak-users.sh`
3. `./scripts/start.sh` -- in a terminal it ends with the browser
   login (as `sam_admin`) and `provision.sh`, which re-creates
   RBAC, models, `max_tokens` and developer-mcp. Run without a
   terminal (CI, an agent), it prints the one follow-up command:
   `./scripts/provision.sh --login`. `docker login` +
   `load-images.sh` are only needed if the private registry
   itself was rebuilt -- images persist outside the namespace.
4. Reinstall the demo, e.g.
   `(cd ../sam-retail-ops-demo && ./install.sh)` (starts the demo
   data stores and re-creates core, overlay, eval package and
   dashboard, including the model bindings)
5. If the desktop app is connected:
   `cd scripts/desktop && ./generate-manifest.sh && ./connect.sh`
   (the MCP tool names embed platform-DB UUIDs, which the rebuild
   changed)

## Observability

SAM is fully wired into the lab's Grafana stack
(`https://monitoring.solace.lab`, folder "SAM": Operations,
Token und Cost, Governance und Security):

- **Metrics**: since 2.348.22 every image-baked component config
  carries an env-gated `management_server` block (off by
  default). `local-k8s-values.yaml` switches it on with one key,
  `environmentVariables.SAM_OBSERVABILITY_ENABLED: "true"`, which
  the chart renders into the env ConfigMap of all three
  components. `/metrics` rides the existing health ports (gwe
  9090, awe/str 8090); `manifests/observability/` adds metrics
  Services + ServiceMonitors. Prometheus picks them up without
  further wiring. The same block has an OTLP push exporter
  (`SAM_OTLP_METRICS`, `SAM_OTLP_ENDPOINT`), left off -- Prometheus
  scrapes. (2.225.14 had no such switch and needed full-file
  config overlays through a Helm post-renderer plugin; both are
  gone.) Key metrics: `sam_entrypoint_*` (request rate
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
- **Traces**: SAM itself emits no OTel spans. Verified on
  2.348.22: the gwe/awe/str binaries link the OTel metric and log
  exporters (`otlpmetric*`, `otlplog*`, `prometheus`) but not the
  trace SDK (`otel/sdk/trace`, `otlptrace*`), and Tempo lists no
  SAM service -- only the broker. A2A traffic
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

- **Metrics gate**: nothing is overlaid any more, so a new
  delivery cannot be silently overridden -- but if it renamed or
  dropped `SAM_OBSERVABILITY_ENABLED`, `/metrics` would just
  vanish. start.sh greps the three baked configs of the pinned
  images for the switch
  (`scripts/observability/check-metrics-gate.sh`) and warns.
- The `management_server` block only works in the MAIN component
  config (extra `--config` files reject root keys: `expected YAML
  list`), and its port is the `--health-addr` port.
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

A new SAM delivery changes the Helm chart, the gwe/str images, the
image-baked component configs and the `sam` CLI's resource schema
at the same time, so an upgrade is a clean rebuild rather than a
rolling `helm upgrade`. The platform database is dropped with the
namespace, so every DB-managed object is re-provisioned afterwards
(`provision.sh`, see "Rebuilding after teardown").

Before starting, have the new delivery package unpacked and the
`sam` CLI of the NEW version installed (see "Installing the sam
CLI"; `SAM_CLI_PATH` in `.env` wins over the PATH, so point it at
the new binary or remove it). The CLI goes first because
preflight section 8 validates the declarative packages with it.

### 1. Review the new delivery (no cluster changes)

```bash
./scripts/upgrade-preflight.sh --new ~/Downloads/SAM*Enterprise*Update*2.348.22*
```

`--new` takes the delivery package directory -- the chart is found
in a subfolder such as `Charts/`, three levels deep at most -- or a
packaged chart (`.tgz`), or an unpacked chart directory. Archives
are classified by content, so the image tarballs in `Images/` are
not mistaken for charts. `--old` defaults to `SAM_CHART_PATH` from
`.env`, i.e. the chart currently deployed.

Delivery package directories are routinely named with spaces, and
sometimes with a trailing one (the 2.348.22 package directory
name ends in a space) or a non-breaking space that no terminal
shows. Use a version-specific glob
(`SAM*Enterprise*Update*<version>*`; a bare `SAM*Enterprise*Update*`
matches every package still in `~/Downloads`, and the previous one
stays there while `.env` points into it) or tab completion rather
than typing the name. When the given
path does not exist but exactly one entry beside it matches once
whitespace and punctuation are ignored, that entry is used and the
substitution is reported; with two candidates it refuses and lists
them.

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
- Do the declarative packages still parse? Section 8 runs
  `sam config plan` (read-only) over every package -- `scripts/`
  rbac, models, entrypoints, desktop, and the demo packages next
  to this directory -- with the CLI `provision.sh` would use
  (`SAM_CLI_PATH` from `.env`, else the PATH). The CLI schema
  moves with the delivery (2.348.22 dropped `claimKey` from
  `rbacClaimMapping` and turned `roleName` into `roleNames`), and
  only a plan shows it. The CLI validates the files only AFTER it
  has reached the platform with a login, so run the preflight
  while the old platform is still up and after
  `sam auth login solace-lab --url https://sam.solace.lab`;
  `NOT VALIDATED` (unreachable, no login) is not a pass.
  "references another package's resources" is fine: a demo's
  `mesh/` needs its `core/` first. `scripts/desktop` targets the
  SAM desktop app and is only validated while that app runs.

Fix `local-k8s-values.yaml` until sections 3 and 7 are clean, and
every section 8 `FAIL` before tearing anything down.

### 2. Tear the old deployment down

```bash
./scripts/stop.sh
```

This removes the Helm release, the namespace with its PVCs and
released PVs, the observability objects in the `monitoring`
namespace, the CoreDNS NodeHosts entry, the cached and now
version-mismatched `sam` CLI plus its login cache, and the
Keycloak client, groups and users, and it drops the SAM queues
on the broker VPN. Uninstall any demo first (see step 8 of the
install walkthrough): nothing of the old version is left in the
cluster then.

### 3. Repoint and re-pin

- `.env`: `SAM_CHART_PATH`, `SAM_APP_IMAGE_TAR`,
  `SAM_STR_IMAGE_TAR` (and `SAM_CLI_TAR` if the package ships a
  CLI) to the new package -- preflight section 6 prints the
  tarball paths as ready-to-paste, already quoted assignments.
  `.env` is sourced, so a path containing a space MUST stay
  quoted or the variable ends up empty. Remove a `SAM_CLI_TAR`
  that still names the OLD tarball. `SAM_CHART_PATH` must be an
  UNPACKED chart directory (`start.sh` checks for `Chart.yaml` in
  it), so unpack the packaged chart once, ideally to a path
  without spaces (command below).
- `local-k8s-values.yaml`: `samDeployment.gwe.image.tag` and
  `samDeployment.str.image.tag` to the versions from preflight
  section 2, plus any values change preflight asked for.
  `scripts/load-images.sh` and `scripts/purge-images.sh` read
  their tags from this file, so there is nothing else to keep in
  sync.

```bash
V=2.1.164   # chart version, preflight section 1
mkdir -p ~/Downloads/solace-agent-mesh-$V
tar -xzf ~/Downloads/SAM*Update*2.348.22*/Charts/solace-agent-mesh-$V.tar.gz \
  -C ~/Downloads/solace-agent-mesh-$V --strip-components=1
```

The Keycloak client was deleted in step 2; re-create it (the
script writes the new secret into `.env`) and the demo users:

```bash
./scripts/setup-keycloak-client.sh
./scripts/setup-keycloak-users.sh
```

### 4. Load the new images

```bash
./scripts/load-images.sh
```

No config re-basing is needed any more: metrics come from the
env switch in `local-k8s-values.yaml`, not from overlaid config
files. `start.sh` checks that the new images still honour that
switch and warns otherwise.

### 5. Install and re-provision

```bash
./scripts/start.sh
```

Run it in a terminal: after the pods are ready it opens the
browser for the `sam` CLI login (log in as `sam_admin`) and runs
`provision.sh` -- RBAC, models, `max_tokens`, developer-mcp. The
demo installs are yours to run afterwards.

### 6. Verify, then drop the old images

Verify first: all pods `Running`, the WebUI on
`https://sam.solace.lab`, `provision.sh` all `OK`, the three SAM
targets `up` in Prometheus. The old gwe/str images stay in
`registry.solace.lab` (and possibly the local Docker daemon),
outside the deleted namespace -- they are the way back until the
new version is proven. Then:

```bash
./scripts/purge-images.sh --dry-run   # review
./scripts/purge-images.sh             # remove
```

It keeps exactly the tags `local-k8s-values.yaml` pins and drops
every other tag of the SAM repositories, so it stays correct
across upgrades. Other repositories (the v1
`solace-agent-mesh-enterprise` and `solace/solace-agent-mesh`
images the lab agents in `sam-solace-lab-agents` run on) are never
touched. `./scripts/stop.sh --purge-images` does the same inline,
which is right for abandoning a version but not for an upgrade.
Registry deletion needs the registry to run with
`REGISTRY_STORAGE_DELETE_ENABLED=true`; the script reports it
rather than failing when it does not. Registry credentials come
from the `docker login` session, also when Docker keeps them in
the macOS keychain (`credsStore: osxkeychain`).

Only the REGISTRY copy is a dependable fallback: the local copy
of an old image may already be gone. Rancher Desktop shares the
Docker image store with k3s, and the kubelet's image garbage
collection deletes unused images when the VM disk crosses its
threshold (85 %). Loading a ~10 GB str image can tip it over; on
the 2.348.22 upgrade the old str 1.50.3 vanished locally during
`start.sh` (`image_gc_manager ... Removing image to free bytes`
in `~/Library/Logs/rancher-desktop/k3s.log`).

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
  (also the key of the extra LiteLLM model aliases)

Consumed by the scripts only (never passed to Helm):

- `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_ADMIN_USER`,
  `KEYCLOAK_ADMIN_PASSWORD` -- Keycloak setup/teardown
- `SAM_CHART_PATH` -- offline chart directory (start.sh)
- `SAM_APP_IMAGE_TAR`, `SAM_STR_IMAGE_TAR` -- image tarballs
  (load-images.sh)
- `SAM_CLI_TAR` / `SAM_CLI_PATH` -- sam CLI (provision.sh and
  the scripts it runs, the preflight and the demo
  install/uninstall scripts, via scripts/lib/)
- `GOOGLE_AI_STUDIO_API_KEY` -- Gemini API key of the
  `google gemini` model alias (scripts/models)
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
- **environmentVariables** -- extra env for all SAM containers:
  `SAM_OBSERVABILITY_ENABLED` switches on `/metrics` (merged with
  the chart's default `NO_PROXY`)
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
  `data_engineer`, `power_user` and `sam_manager`. The last one
  targets the built-in role `sam_manager` (new in 2.348.22,
  created by the platform): full control over agents, builder,
  connectors, models, entrypoints, evals, skills, tools and
  workflows, but no RBAC -- separation of duties next to
  `sam_admin`, who alone decides who may do what. The claim they
  match is
  deployment-wide since 2.348.22 (`sam.oauthProvider.claimKey`,
  default `groups`, which the Keycloak group mapper emits), no
  longer a field of each mapping
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
    upgrade-preflight.sh          Compare a new delivery with
                                  the deployed one
    start.sh                      Deploy SAM (local chart path)
    provision.sh                  DB-managed content after an
                                  install (RBAC, models, MCP)
    stop.sh                       Full teardown
    lib/                          Shared helpers (sam CLI, .env)
    rbac/                         Declarative RBAC (sam config)
    entrypoints/                  Platform developer-mcp MCP
                                  entrypoint (declarative, v2)
    models/                       Model aliases + max_tokens
    observability/                Metrics gate check, Grafana
                                  platform-DB grant
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
