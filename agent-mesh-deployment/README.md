# Agent Mesh Deployment

Helm-based deployment of Solace Agent Mesh (SAM) on Kubernetes.
This deployment connects to the `sam` VPN on `solace-1` created
by the [event-mesh-deployment](../event-mesh-deployment/README.md)
and requires a running Solace Event Mesh as its messaging backbone.

## Prerequisites

- Kubernetes cluster (local or remote)
- Helm 3
- kubectl configured for your cluster
- NGINX Ingress Controller with cert-manager
- Solace Event Mesh running
  (see `../event-mesh-deployment/start.sh`)
- Keycloak instance with a `solace-lab` realm
  (see `solace-lab-infrastructure/keycloak`)
- LLM service endpoint (e.g. LiteLLM proxy)

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

## Quick Start

### 1. Prepare credentials

```bash
cp .env.example .env
```

Edit `.env` and set at minimum `LLM_SERVICE_API_KEY`.
The Keycloak variables can be populated automatically
in the next step.

The file contains:

- **SAM_NAMESPACE** -- Kubernetes namespace (`sam-ent-k8s`)
- **SAM_RELEASE** -- Helm release name (`agent-mesh`)
- **SAM_SESSION_SECRET_KEY** -- Session signing secret
- **KEYCLOAK_URL** -- Keycloak base URL
- **KEYCLOAK_REALM** -- Keycloak realm name
- **KEYCLOAK_ADMIN_USER** / **KEYCLOAK_ADMIN_PASSWORD** --
  Keycloak admin credentials (for client setup script)
- **KEYCLOAK_CLIENT_ID** -- OIDC client ID
- **KEYCLOAK_CLIENT_SECRET** -- OIDC client secret
- **KEYCLOAK_REDIRECT_URI** -- OIDC redirect URI
- **KEYCLOAK_ISSUER** -- OIDC issuer URL
- **LLM_SERVICE_API_KEY** -- API key for the LLM service
- **REGISTRY_PULL_SECRET** -- Name of the image pull secret

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

### 3. Deploy

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

### 4. Teardown

```bash
./scripts/stop.sh
```

This uninstalls the Helm release, deletes PVCs, removes
the namespace, and deletes the Keycloak OIDC client.

## Upgrade

To upgrade SAM to a new version:

```bash
helm repo update solace-agent-mesh
helm upgrade agent-mesh \
  solace-agent-mesh/solace-agent-mesh \
  -n sam-ent-k8s \
  --reuse-values \
  --set samDeployment.image.tag=<new-sam-tag> \
  --set samDeployment.agentDeployer.image.tag=<new-deployer-tag>
```

To inspect current values:

```bash
helm get values agent-mesh -n sam-ent-k8s
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

### Secrets (via .env)

All sensitive values are kept out of the Helm values file and
injected at deploy time via `--set` flags. See `.env.example`
for the full list.

### Helm Values (local-k8s-values.yaml)

Non-sensitive configuration is defined in `local-k8s-values.yaml`.
Key sections:

- **sam** -- Core SAM config (RBAC, roles, task logging)
- **broker** -- Solace broker connection
  (`ws://host.docker.internal:8008`, VPN `sam`)
- **llmService** -- LLM model selection and endpoint
- **ingress** -- NGINX ingress with TLS via cert-manager
- **samDeployment** -- Image repositories, tags, and deployer

### Broker Connection

SAM connects to the `sam` VPN on `solace-1` from the
event-mesh-deployment:

- URL: `ws://host.docker.internal:8008`
- VPN: `sam`
- Username: `default`
- Password: `default`

### RBAC Roles

The deployment defines four custom roles in addition to the
built-in `sam_admin` and `sam_user` roles:

- **operator** -- System operator with basic and advanced
  tool access
- **viewer** -- Read-only access
- **data_engineer** -- Data tools and connector read access
- **power_user** -- Broad tool access with agent builder
  and connector management

Role assignment is driven by Keycloak group claims. Users
whose claims do not match any mapping receive the `viewer`
role by default.

## Directory Structure

```text
agent-mesh-deployment/
  .env.example                    Credentials template
  .gitignore                      Ignores .env
  local-k8s-values.yaml           Helm values (no secrets)
  scripts/
    setup-keycloak-client.sh      Create OIDC client
    teardown-keycloak-client.sh   Delete OIDC client
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
