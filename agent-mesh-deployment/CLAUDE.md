# CLAUDE.md -- Agent Mesh Deployment

## Overview

Helm-based deployment of Solace Agent Mesh (SAM) on Kubernetes.
Depends on the event-mesh-deployment for broker connectivity
(sam VPN on solace-1) and on solace-lab-infrastructure for
the surrounding cluster services.

## Cluster Dependencies

This deployment assumes the following cluster state, provisioned
by the companion repo
[`solace-lab-infrastructure`](https://github.com/martensa/solace-lab-infrastructure):

- NGINX Ingress Controller (namespace `ingress-nginx`)
- cert-manager + ClusterIssuer `solace-lab-ca-issuer`
- trust-manager + ConfigMap `solace-lab-ca-trust-bundle`
  distributed to all namespaces (used by the Kyverno policy
  `inject-solace-lab-ca-trust-bundle` which mounts the CA
  bundle at `/etc/ssl/certs/ca-certificates.crt` in every
  pod AND sets `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` env
  vars so Python apps automatically pick up the OS trust
  store)
- Private registry at `registry.solace.lab` with Kyverno policy
  `inject-registry-pull-secret` auto-wiring `imagePullSecrets`
- Keycloak at `auth.solace.lab` with the `solace-lab` realm
  (and an auth.solace.lab entry in CoreDNS NodeHosts so the SAM
  pods can reach it via the external hostname)

In addition to the above, `start.sh` registers `sam.solace.lab`
in CoreDNS NodeHosts during deployment (and `stop.sh` removes
it again). SAM makes internal self-calls to its own external
URL during the OAuth flow (WebUI -> Platform Service), so the
hostname must resolve inside the cluster too. This follows the
same decentralized convention as solace-lab-infrastructure:
each component manages its own hostname entry.

Do not re-create any of these resources from this repository.
All Keycloak-side configuration this repo owns is scoped to
`solace-agent-mesh` OIDC client plus `viewer`, `data_engineer`,
`power_user` groups and demo users within the `solace-lab` realm.

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
