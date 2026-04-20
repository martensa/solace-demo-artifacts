# CLAUDE.md

## Project Overview

This repository contains deployment artifacts for a comprehensive
Solace demo environment. It includes a two-broker Solace Event
Mesh with distributed tracing and Event Portal integration, and a
Solace Agent Mesh deployment on Kubernetes.

The Agent Mesh deployment depends on cluster infrastructure from
the companion repository
[`solace-lab-infrastructure`](https://github.com/martensa/solace-lab-infrastructure)
(NGINX Ingress, cert-manager/PKI, private registry, Keycloak,
Kyverno policies). The Event Mesh deployment is standalone and
has no infrastructure dependency.

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
cp .env.example .env                 # edit LLM_SERVICE_API_KEY
./scripts/setup-keycloak-client.sh   # creates OIDC client
# paste the printed client secret into .env
./scripts/setup-keycloak-users.sh    # creates groups + demo users
./scripts/start.sh                   # helm install with --set
./scripts/stop.sh                    # full teardown incl. Keycloak
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

- Deployment-specific secrets (Keycloak OIDC client secret,
  LLM API key) live in `.env` (gitignored) and are injected
  via `--set` flags in `start.sh`. Only `.env.example` with
  placeholder values is checked in.
- Non-sensitive config and demo-only values (session key,
  broker default password, DNS name, pull secret name) live
  in `local-k8s-values.yaml` and are safe to commit.
- `start.sh` and `stop.sh` hardcode the release name
  (`agent-mesh`) and namespace (`sam-solace-lab`).

## Secrets

- Event Mesh: Credentials in `ema_config_keys.env` and
  `amartens_ema.yml` are hardcoded intentionally for local
  demo use. Do not externalize them.
- Agent Mesh: Deployment-specific secrets (Keycloak client
  secret, LLM API key) live in `.env` (gitignored) and are
  injected at deploy time. Never add real production
  credentials to `local-k8s-values.yaml`.

## Writing Documentation

README files are written in English. Avoid special characters
and ensure markdown linting passes
(`npx markdownlint-cli <file>`). Key rules:

- Lines must not exceed 80 characters (MD013). Use line
  breaks in prose and prefer lists over wide tables.
- URLs must be wrapped in backticks or angle brackets, never
  bare (MD034).
- Avoid HTML in markdown files.
