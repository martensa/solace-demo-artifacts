# Solace Demo Artifacts

A collection of deployment artifacts for building a comprehensive
Solace demo environment. This repository covers the full Solace
demo spectrum including Event Mesh, Solace Agent Mesh, Distributed
Tracing, Kafka Bridge, Event Portal, and Schema Registry.

## Repository Structure

```text
solace-demo-artifacts/
  event-mesh-deployment/   Core Solace Event Mesh infrastructure
  agent-mesh-deployment/   Solace Agent Mesh on Kubernetes
  micro-integrations/      Standalone Solace Micro-Integrations
    topic-compaction/      Kafka-style log compaction over Solace
    db-jpa/                Database <-> Solace connector (JPA)
```

## Infrastructure Prerequisites

The `agent-mesh-deployment` component depends on a Kubernetes cluster
with a set of shared infrastructure services. These are not part of
this repository -- they live in the companion repository
[`solace-lab-infrastructure`](https://github.com/martensa/solace-lab-infrastructure)
and must be installed first.

Required components from `solace-lab-infrastructure`:

- **`ingress/`** -- NGINX Ingress Controller
- **`pki/`** -- cert-manager, CA hierarchy (`solace-lab-ca-issuer`),
  trust-manager (CA trust bundle), Kyverno policies for
  pull-secret and CA-trust injection
- **`registry/`** -- Private Docker registry at
  `registry.solace.lab` with automatic pull-secret distribution
- **`keycloak/`** -- Keycloak Identity Provider at `auth.solace.lab`
  with the `solace-lab` realm (provides `admin`, `user`,
  `alexander.martens` realm users). The Keycloak setup also
  registers `auth.solace.lab` in CoreDNS NodeHosts so in-cluster
  pods can resolve the hostname for OIDC discovery.

The `event-mesh-deployment` component is standalone and has no
dependency on `solace-lab-infrastructure`.

## Components

### Event Mesh Deployment

A fully automated, Docker-based deployment of a two-broker Solace
Event Mesh with DMR (Dynamic Message Routing), distributed tracing
via OpenTelemetry and Jaeger, and Event Management Agent
integration with Solace Event Portal.

See
[event-mesh-deployment/README.md](event-mesh-deployment/README.md)
for setup instructions and architecture details.

### Agent Mesh Deployment

Helm-based deployment of Solace Agent Mesh (SAM) on Kubernetes.
Connects to the `sam` VPN on `solace-1` created by the Event Mesh
Deployment. Includes OIDC authentication via Keycloak, RBAC, and
LLM service integration.

See
[agent-mesh-deployment/README.md](agent-mesh-deployment/README.md)
for setup instructions and architecture details.

### Micro-Integrations

Standalone Solace Micro-Integrations under `micro-integrations/`,
each self-contained with its own README:

- **`topic-compaction/`** -- a Solace-native alternative to Kafka
  log compaction (last-value store, replay, lookup, TTL retention).
- **`db-jpa/`** -- moves data between a relational database and a
  Solace broker via JPA; includes a runtime connector, a low-code
  Connector Designer, and a JPA entity-generator CLI.

See
[micro-integrations/topic-compaction/README.md](micro-integrations/topic-compaction/README.md)
and
[micro-integrations/db-jpa/README.md](micro-integrations/db-jpa/README.md).

## Prerequisites

- Docker and Docker Compose (for Event Mesh)
- Terraform 1.5 or later (for Event Mesh)
- Helm 3 and kubectl (for Agent Mesh)
- `bash`, `curl`, `jq`, `openssl`
- Cluster infrastructure from
  [`solace-lab-infrastructure`](https://github.com/martensa/solace-lab-infrastructure)
  installed (only for Agent Mesh)

## Quick Start

Start the Event Mesh first, then deploy Agent Mesh:

```bash
# Event Mesh (standalone)
cd event-mesh-deployment
./start.sh

# Agent Mesh (requires solace-lab-infrastructure deployed first)
cd ../agent-mesh-deployment
cp .env.example .env                 # edit LLM_SERVICE_API_KEY
./scripts/setup-keycloak-client.sh   # creates OIDC client
# paste the printed client secret into .env
./scripts/setup-keycloak-users.sh    # creates groups + demo users
./scripts/start.sh                   # helm install
```

See the component READMEs for full details.
