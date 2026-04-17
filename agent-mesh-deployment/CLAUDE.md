# CLAUDE.md -- Agent Mesh Deployment

## Overview

Helm-based deployment of Solace Agent Mesh (SAM) on Kubernetes.
Depends on the event-mesh-deployment for broker connectivity
(sam VPN on solace-1).

## Start and Stop

```bash
./scripts/setup-keycloak-client.sh  # create OIDC client first
./scripts/start.sh                  # helm install with --set
./scripts/stop.sh                   # teardown incl. Keycloak client
```

## Secrets Handling

- Sensitive values are never stored in `local-k8s-values.yaml`.
- They live in `.env` (gitignored) and are injected via
  `--set` flags at deploy time.
- `.env.example` is the checked-in template with placeholders.
- `start.sh` validates that all required variables are set
  before deploying.

## Key Files

- `local-k8s-values.yaml` -- Non-sensitive Helm values
  (safe to commit)
- `.env.example` -- Template for secrets and deploy config
- `scripts/setup-keycloak-client.sh` -- Creates the OIDC
  client in Keycloak via Admin REST API
- `scripts/teardown-keycloak-client.sh` -- Deletes the OIDC
  client (called automatically by stop.sh)
- `scripts/start.sh` -- Sources `.env`, runs helm install
- `scripts/stop.sh` -- Full teardown including Keycloak client
