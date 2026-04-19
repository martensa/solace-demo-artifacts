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
```

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
Deployment. Includes OIDC authentication via Keycloak, RBAC,
and LLM service integration.

See
[agent-mesh-deployment/README.md](agent-mesh-deployment/README.md)
for setup instructions and architecture details.

## Prerequisites

- Docker and Docker Compose
- Terraform 1.5 or later
- Helm 3 and kubectl
- curl

## Quick Start

Start the Event Mesh first, then deploy Agent Mesh:

```bash
cd event-mesh-deployment
./start.sh

cd ../agent-mesh-deployment
cp .env.example .env                 # edit LLM_SERVICE_API_KEY
./scripts/setup-keycloak-client.sh   # creates OIDC client
# paste the printed client secret into .env
./scripts/setup-keycloak-users.sh    # creates groups + demo users
./scripts/start.sh                   # helm install
```

See the component READMEs for full details.
