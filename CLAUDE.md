# CLAUDE.md

## Project Overview

This repository contains deployment artifacts for a comprehensive Solace demo
environment. The primary component is a two-broker Solace Event Mesh with
distributed tracing and Event Portal integration.

## Tech Stack

- Docker Compose for container orchestration
- Terraform with the `solaceproducts/solacebroker` provider for broker configuration
- OpenTelemetry Collector with Solace receiver plugin for distributed tracing
- Jaeger for trace visualization
- Solace Event Management Agent (EMA) for Event Portal integration

## Start and Stop

```bash
cd event-mesh-deployment
./start.sh   # brings up containers, runs terraform, enables DMR links
./stop.sh    # tears down containers and cleans up generated files
```

## Terraform Conventions

- Two aliased providers (`solacebroker.solace_1` and `solacebroker.solace_2`)
  are defined in `provider.tf`. Every module call must pass
  `providers = { solacebroker = solacebroker.<alias> }`.
- Reusable modules live in `terraform/modules/` (vpn, client, dmr, telemetry, queue).
- DMR cluster links are created disabled by Terraform. The `start.sh` script
  enables them via SEMP API calls after Terraform applies. The `dmr_enabled`
  variable in `terraform.tfvars` controls Terraform-managed link state but the
  SEMP calls in `start.sh` are the authoritative enablement step.

## Secrets

Credentials in `ema_config_keys.env` and `amartens_ema.yml` are hardcoded
intentionally for local demo use. Do not treat these as templates to
externalize -- they are meant to work out of the box.

## Writing Documentation

README files are written in English. Avoid special characters and ensure
markdown linting passes (`npx markdownlint-cli <file>`). Key rules:

- Lines must not exceed 80 characters (MD013). Use line breaks in
  prose and prefer lists over wide tables.
- URLs must be wrapped in backticks or angle brackets, never bare
  (MD034).
- Avoid HTML in markdown files.
