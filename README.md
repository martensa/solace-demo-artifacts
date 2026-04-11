# Solace Demo Artifacts

A collection of deployment artifacts for building a comprehensive Solace demo
environment. This repository covers the full Solace demo spectrum including
Event Mesh, Solace Agent Mesh, Distributed Tracing, Kafka Bridge, Event Portal,
and Schema Registry.

## Repository Structure

```text
solace-demo-artifacts/
  event-mesh-deployment/   Core infrastructure for the Solace Event Mesh
```

## Components

### Event Mesh Deployment

A fully automated, Docker-based deployment of a two-broker Solace Event Mesh
with DMR (Dynamic Message Routing), distributed tracing via OpenTelemetry and
Jaeger, and Event Management Agent integration with Solace Event Portal.

See [event-mesh-deployment/README.md](event-mesh-deployment/README.md) for
setup instructions and architecture details.

## Prerequisites

- Docker and Docker Compose
- Terraform 1.5 or later
- curl

## Quick Start

```bash
cd event-mesh-deployment
./start.sh
```

See the component README for full details.
