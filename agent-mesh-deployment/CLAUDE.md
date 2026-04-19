# CLAUDE.md -- Agent Mesh Deployment

## Overview

Helm-based deployment of Solace Agent Mesh (SAM) on Kubernetes.
Depends on the event-mesh-deployment for broker connectivity
(sam VPN on solace-1).

## Start and Stop

```bash
./scripts/setup-keycloak-client.sh  # create OIDC client first
./scripts/setup-keycloak-users.sh   # create groups and demo users
./scripts/start.sh                  # helm install with --set
./scripts/stop.sh                   # full teardown
```

## Secrets Handling

- Deployment-specific secrets (Keycloak OIDC client secret
  and LLM API key) live in `.env` (gitignored) and are
  injected via `--set` flags at deploy time.
- `.env.example` is the checked-in template with placeholders.
- `start.sh` validates that the required `.env` variables
  are set and not left at `changeme` before deploying.
- Non-sensitive demo-only values (session key, broker
  default password, DNS name, pull secret name) are kept
  in `local-k8s-values.yaml` for reproducibility.

## References

- SAM product docs:
  <https://solacelabs.github.io/solace-agent-mesh/docs/documentation/getting-started>
- SAM Helm chart docs:
  <https://solaceproducts.github.io/solace-agent-mesh-helm-quickstart/docs/>

RBAC scope syntax follows the Helm Quickstart style
(resource-centric, e.g. `artifact:read`, `sam:connectors:*`)
rather than the Enterprise production-ready style
(action-centric, e.g. `tool:basic:*`, `monitor/...`).
Do not mix the two styles in `local-k8s-values.yaml`.

## Key Files

- `local-k8s-values.yaml` -- Non-sensitive Helm values
  (safe to commit)
- `.env.example` -- Template for secrets and deploy config
- `scripts/setup-keycloak-client.sh` -- Creates the OIDC
  client in Keycloak via Admin REST API
- `scripts/teardown-keycloak-client.sh` -- Deletes the OIDC
  client (called automatically by stop.sh)
- `scripts/setup-keycloak-users.sh` -- Creates groups and
  demo users in Keycloak
- `scripts/teardown-keycloak-users.sh` -- Deletes groups
  and demo users (called automatically by stop.sh)
- `scripts/start.sh` -- Sources `.env`, runs helm install
- `scripts/stop.sh` -- Full teardown including Keycloak client
