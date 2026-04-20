# Agent Mesh Deployment

Helm-based deployment of Solace Agent Mesh (SAM) on Kubernetes.
This deployment connects to the `sam` VPN on `solace-1` created
by the [event-mesh-deployment](../event-mesh-deployment/README.md)
and requires a running Solace Event Mesh as its messaging backbone.

## Prerequisites

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
    `/etc/ssl/certs/ca-certificates.crt` in every pod)
  - Kyverno policy `inject-registry-pull-secret`
- **Private Registry** -- `registry/`
  - Available at `https://registry.solace.lab`
  - Holds the SAM enterprise and agent-deployer images
- **Keycloak** -- `keycloak/`
  - OIDC provider at `https://auth.solace.lab` with the
    `solace-lab` realm
  - The setup script registers `auth.solace.lab` in CoreDNS
    NodeHosts so cluster-internal pods can resolve the hostname

### Additional Services

- **Solace Event Mesh** running locally
  (see [`../event-mesh-deployment/`](../event-mesh-deployment/))
  with the `sam` VPN on `solace-1`
- **LLM Service** endpoint (e.g. a LiteLLM proxy) with an API key

### Local CLI Tools

- `kubectl` configured for your cluster
- `helm` 3
- `bash`, `curl`, `jq`, `openssl`

## Architecture Overview

```text
+---------------------+
|   Keycloak (OIDC)   |
+----------+----------+
           |
+----------+----------+     +------------------+
| Solace Agent Mesh   |     |   LLM Service    |
| (sam.solace.lab)    +---->| (LiteLLM Proxy)  |
+----------+----------+     +------------------+
           |
           | ws://host.docker.internal:8008
           |
+----------+----------+
|  solace-1 / VPN sam |
|  (Event Mesh)       |
+---------------------+
```

SAM connects to the `sam` Message VPN on `solace-1` via WebSocket.
The broker provides the messaging backbone for agent-to-agent
communication, task routing, and event distribution.

Keycloak, the ingress controller, the private registry and the
PKI chain visible above are deployed by
[`solace-lab-infrastructure`](https://github.com/martensa/solace-lab-infrastructure).
This deployment only provisions SAM itself and registers an
OIDC client plus demo users in the existing `solace-lab` realm.

## Quick Start

### 1. Prepare credentials

```bash
cp .env.example .env
```

Edit `.env` and set at minimum `LLM_SERVICE_API_KEY`.
The Keycloak variables can be populated automatically
in the next step.

The file contains:

- **KEYCLOAK_URL** -- Keycloak base URL
- **KEYCLOAK_REALM** -- Keycloak realm name
- **KEYCLOAK_ADMIN_USER** / **KEYCLOAK_ADMIN_PASSWORD** --
  Keycloak admin credentials (for client setup script)
- **KEYCLOAK_CLIENT_ID** -- OIDC client ID
- **KEYCLOAK_CLIENT_SECRET** -- OIDC client secret
- **KEYCLOAK_ISSUER** -- OIDC issuer URL
- **LLM_SERVICE_API_KEY** -- API key for the LLM service

Deployment-level settings (namespace `sam-solace-lab`, release name
`agent-mesh`, DNS name `sam.solace.lab`, image pull secret
`registry-pull-secret`) are defined in the scripts and the
Helm values file.

### 2. Create the Keycloak OIDC client

```bash
./scripts/setup-keycloak-client.sh
```

This creates a confidential OIDC client `solace-agent-mesh`
in the `solace-lab` realm via the Keycloak Admin REST API.
It also adds a group membership mapper so the `groups` claim
is included in tokens (required for SAM RBAC).

The script prints the generated client secret. Copy it into
your `.env` file as `KEYCLOAK_CLIENT_SECRET`.

### 3. Create Keycloak groups and demo users

```bash
./scripts/setup-keycloak-users.sh
```

This creates five groups (`admin`, `user`, `viewer`,
`data_engineer`, `power_user`) and three demo users
(`viewer`, `data_engineer`, `power_user`) with password
equal to the username. Each user is assigned to the group
matching their name. Pre-existing `admin` and `user`
users are automatically assigned to their groups.

### 4. Deploy

```bash
./scripts/start.sh
```

The script performs the following steps:

1. Validates that all required variables in `.env` are set
2. Adds and updates the Solace Agent Mesh Helm repository
3. Creates the Kubernetes namespace
4. Runs `helm upgrade --install` with the values file and
   injects secrets via `--set` flags
5. Waits for pods to become ready
6. Prints the Helm release status and pod list

### 5. Teardown

```bash
./scripts/stop.sh
```

This uninstalls the Helm release, deletes PVCs, removes
the namespace, removes the Keycloak users and groups, and
deletes the Keycloak OIDC client.

## Upgrade

To upgrade SAM to a new version:

```bash
helm repo update solace-agent-mesh
helm upgrade agent-mesh \
  solace-agent-mesh/solace-agent-mesh \
  -n sam-solace-lab \
  --reuse-values \
  --set samDeployment.image.tag=<new-sam-tag> \
  --set samDeployment.agentDeployer.image.tag=<new-deployer-tag>
```

To inspect current values:

```bash
helm get values agent-mesh -n sam-solace-lab
```

## Loading Images into a Local Registry

If your cluster uses a private registry, load the images manually:

```bash
docker load -i solace-agent-mesh-enterprise-<tag>.tar.gz
docker tag solace-agent-mesh-enterprise:<tag> \
  registry.solace.lab/solace-agent-mesh-enterprise:<tag>
docker push \
  registry.solace.lab/solace-agent-mesh-enterprise:<tag>

docker load -i sam-agent-deployer-<tag>.tar.gz
docker tag sam-agent-deployer:<tag> \
  registry.solace.lab/sam-agent-deployer:<tag>
docker push \
  registry.solace.lab/sam-agent-deployer:<tag>
```

## Configuration

### Environment variables (via .env)

The following `.env` values are passed to Helm via `--set`
at deploy time and overlay the empty placeholders in
`local-k8s-values.yaml`:

- `KEYCLOAK_ISSUER` -> `sam.oauthProvider.oidc.issuer`
- `KEYCLOAK_CLIENT_ID` -> `sam.oauthProvider.oidc.clientId`
- `KEYCLOAK_CLIENT_SECRET` -> `sam.oauthProvider.oidc.clientSecret`
- `LLM_SERVICE_API_KEY` -> `llmService.llmServiceApiKey`

Keycloak admin credentials (`KEYCLOAK_URL`, `KEYCLOAK_REALM`,
`KEYCLOAK_ADMIN_USER`, `KEYCLOAK_ADMIN_PASSWORD`) are only
consumed by the Keycloak setup and teardown scripts and
never passed to Helm.

### Helm Values (local-k8s-values.yaml)

All non-sensitive configuration plus demo-only defaults are
defined in `local-k8s-values.yaml`. Key sections:

- **sam** -- Core SAM config (session key, RBAC, roles,
  task logging, OIDC provider structure)
- **broker** -- Solace broker connection
  (`ws://host.docker.internal:8008`, VPN `sam`,
  default credentials from event-mesh-deployment)
- **llmService** -- LLM model selection and endpoint
- **ingress** -- NGINX ingress host (`sam.solace.lab`)
  with TLS via cert-manager
- **samDeployment** -- Image repositories, tags, deployer,
  and image pull secret name (`registry-pull-secret`)

### Broker Connection

SAM connects to the `sam` VPN on `solace-1` from the
event-mesh-deployment:

- URL: `ws://host.docker.internal:8008`
- VPN: `sam`
- Username: `default`
- Password: `default`

### RBAC Roles

The deployment defines three custom roles in addition to
the built-in `sam_admin` (full access) and `sam_user`
(basic access) roles. Scope syntax follows the SAM Helm
Quickstart documentation:

- **viewer** -- Read-only access to deployments, artifacts,
  and connectors
- **data_engineer** -- Data tools plus artifact and
  connector read/write access
- **power_user** -- Broad tool access with agent builder
  read and full connector management

Role assignment is driven by Keycloak group claims. The
`setup-keycloak-users.sh` script creates the following
group-to-role mapping:

- Group `admin` -- `sam_admin`
- Group `user` -- `sam_user`
- Group `viewer` -- `viewer`
- Group `data_engineer` -- `data_engineer`
- Group `power_user` -- `power_user`

Users whose claims do not match any mapping receive the
`viewer` role by default.

## Directory Structure

```text
agent-mesh-deployment/
  .env.example                    Credentials template
  .gitignore                      Ignores .env
  local-k8s-values.yaml           Helm values (no secrets)
  scripts/
    setup-keycloak-client.sh      Create OIDC client
    teardown-keycloak-client.sh   Delete OIDC client
    setup-keycloak-users.sh       Create groups + demo users
    teardown-keycloak-users.sh    Delete groups + demo users
    start.sh                      Deploy SAM
    stop.sh                       Full teardown
  CLAUDE.md                       Claude Code instructions
  README.md                       This file
```

## Accessing SAM

Once deployed, SAM is available at:

- Frontend: `https://sam.solace.lab`
- Platform API: `https://sam.solace.lab/api`

Ensure your DNS or `/etc/hosts` points `sam.solace.lab` to
your ingress controller IP.

## References

- Solace Agent Mesh product documentation:
  <https://solacelabs.github.io/solace-agent-mesh/docs/documentation/getting-started>
- Solace Agent Mesh Helm chart documentation:
  <https://solaceproducts.github.io/solace-agent-mesh-helm-quickstart/docs/>
