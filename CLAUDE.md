# CLAUDE.md

## Project Overview

This repository contains deployment artifacts for a comprehensive
Solace demo environment. It includes a two-broker Solace Event
Mesh with distributed tracing and Event Portal integration, and a
Solace Agent Mesh deployment on Kubernetes.

## Tech Stack

- Docker Compose for container orchestration (event-mesh)
- Terraform with the `solaceproducts/solacebroker` provider
  for broker configuration (event-mesh)
- Helm for Kubernetes deployments (agent-mesh)
- OpenTelemetry Collector with Solace receiver plugin for
  distributed tracing
- Jaeger for trace visualization
- Solace Event Management Agent (EMA) for Event Portal
  integration
- Solace Agent Mesh (SAM) with Keycloak OIDC and LLM
  service integration

## Start and Stop

### Event Mesh (start first)

```bash
cd event-mesh-deployment
./start.sh   # brings up containers, runs terraform, enables DMR
./stop.sh    # tears down containers and cleans up generated files
```

### Agent Mesh (requires Event Mesh running)

```bash
cd agent-mesh-deployment
cp .env.example .env   # edit with your credentials
./scripts/start.sh   # helm install with secrets via --set
./scripts/stop.sh    # helm uninstall, delete PVCs and namespace
```

## Terraform Conventions

- Two aliased providers (`solacebroker.solace_1` and
  `solacebroker.solace_2`) are defined in `provider.tf`.
  Every module call must pass
  `providers = { solacebroker = solacebroker.<alias> }`.
- Reusable modules live in `terraform/modules/`
  (vpn, client, dmr, telemetry, queue).
- DMR cluster links are created disabled by Terraform.
  The `start.sh` script enables them via SEMP API calls
  after Terraform applies. The `dmr_enabled` variable in
  `terraform.tfvars` controls Terraform-managed link state
  but the SEMP calls in `start.sh` are the authoritative
  enablement step.

## Helm Conventions (agent-mesh-deployment)

- Sensitive values (API keys, OIDC secrets, session secret)
  are never stored in the Helm values file. They are defined
  in `.env` and injected via `--set` flags in `start.sh`.
- The `.env` file is gitignored. Only `.env.example` with
  placeholder values is checked in.
- `local-k8s-values.yaml` contains all non-sensitive
  configuration and is safe to commit.

## Secrets

- Event Mesh: Credentials in `ema_config_keys.env` and
  `amartens_ema.yml` are hardcoded intentionally for local
  demo use. Do not externalize them.
- Agent Mesh: Secrets live in `.env` (gitignored) and are
  injected at deploy time. Never add real credentials to
  `local-k8s-values.yaml`.

## Writing Documentation

README files are written in English. Avoid special characters
and ensure markdown linting passes
(`npx markdownlint-cli <file>`). Key rules:

- Lines must not exceed 80 characters (MD013). Use line
  breaks in prose and prefer lists over wide tables.
- URLs must be wrapped in backticks or angle brackets, never
  bare (MD034).
- Avoid HTML in markdown files.
