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
- **Retail demo databases** (for the retail demo agents): a
  standalone postgres docker container on the host (containers
  `postgres` + `pgadmin`, managed outside this repo) serving
  `retail_crm`, `retail_oms` and `retail_pdm` on port 5432. The
  connectors reach it via `host.docker.internal:5432`. Note: the
  container stays `Exited` after a host restart -- start it with
  `docker start postgres pgadmin`.

### Local CLI Tools

- `kubectl` configured for your cluster
- `helm` 3
- `docker` (for the image load step)
- `bash`, `curl`, `jq`, `python3`
- the `sam` CLI from the delivery package (see `.env` variables
  `SAM_CLI_PATH` / `SAM_CLI_TAR`)

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

### 7. Start the retail demo databases

The retail demo agents query three postgres databases that live in
a standalone docker container on the host (outside this repo):

```bash
docker start postgres pgadmin
```

The container serves `retail_crm`, `retail_oms` and `retail_pdm`
on port 5432 and stays `Exited` after host restarts.

### 8. Provision the retail demo (agents, workflow, MCP)

```bash
cd scripts/agents && ./create.sh --deploy
```

Creates and deploys the connectors, schema skills, query-expert
agents, the `retail-360-report` workflow and the MCP entrypoint.
See [`scripts/agents/README.md`](scripts/agents/README.md).
Requires the `sam auth login` from step 6.

### 9. Set the model output limit

```bash
cd scripts/models && ./set-max-tokens.sh
```

Sets `modelParams.max_tokens` (default 16384) on the `general`
model and restarts the agents. Without it the chart-seeded empty
`modelParams` reintroduce the tool-call truncation failure
documented in [`scripts/models/README.md`](scripts/models/README.md).
Repeat with `--model-alias planning` and `--model-alias report_gen`.

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
the retail connectors, skills, agents, workflow and MCP
entrypoint, and the model `max_tokens` tuning. The Keycloak
client is deleted too, so the sam CLI login cache is invalid.
To rebuild:

1. `docker start postgres pgadmin` (retail demo DBs, see step 7)
2. `./scripts/setup-keycloak-client.sh` -- paste the NEW client
   secret into `.env`
3. `./scripts/setup-keycloak-users.sh`
4. `./scripts/start.sh` (`docker login` + `load-images.sh` are
   only needed if the private registry itself was rebuilt --
   images persist outside the namespace)
5. `sam auth login solace-lab --url https://sam.solace.lab`
   (as `sam_admin`)
6. `./scripts/rbac/apply-rbac.sh`
7. `cd scripts/agents && ./create.sh --deploy`
8. `cd scripts/models && ./set-max-tokens.sh` (plus
   `--model-alias planning` and `--model-alias report_gen`)

## Upgrade

To upgrade SAM to a new version, point `.env` at the new delivery
package (chart directory and image tarballs), update the image
tags in `local-k8s-values.yaml`
(`samDeployment.gwe.image.tag`, `samDeployment.str.image.tag`)
and the constants in `scripts/load-images.sh`, then:

```bash
./scripts/load-images.sh
./scripts/start.sh
```

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
  agents/create.sh, models/set-max-tokens.sh via scripts/lib/)
- `RETAIL_DB_USERNAME` / `RETAIL_DB_PASSWORD` -- retail connector
  credentials (optional; manifest defaults postgres/postgres)

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
    start.sh                      Deploy SAM (local chart path)
    stop.sh                       Full teardown
    lib/                          Shared helpers (sam CLI, .env)
    rbac/                         Declarative RBAC (sam config)
    agents/                       Retail demo provisioning
                                  (declarative, sam config, v2)
    models/                       Model tuning via sam CLI (v2)
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
