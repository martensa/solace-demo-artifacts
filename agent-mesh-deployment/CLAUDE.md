# CLAUDE.md -- Agent Mesh Deployment

## Overview

Helm-based deployment of Solace Agent Mesh (SAM) v2 (Go stack) on
Kubernetes. Three components: gwe (Entrypoint Executor: WebUI +
platform API, the only ingress backend), awe (Agent-Workflow
Executor) and str (Secure Tool Runtime). There is no
agent-deployer in v2. Depends on the event-mesh-deployment for
broker connectivity (sam VPN on solace-1,
`global.broker.embedded: false`) and on solace-lab-infrastructure
for the surrounding cluster services.

The chart and images come from the offline SAM delivery package
and are NOT checked in. `.env` carries the local paths:
`SAM_CHART_PATH` (unpacked chart), `SAM_APP_IMAGE_TAR` /
`SAM_STR_IMAGE_TAR` (image tarballs for `load-images.sh`),
`SAM_CLI_TAR` (sam CLI for the RBAC step).

## Cluster Dependencies

This deployment assumes the following cluster state, provisioned
by the companion repo
[`solace-lab-infrastructure`](https://github.com/martensa/solace-lab-infrastructure):

- NGINX Ingress Controller (namespace `ingress-nginx`)
- cert-manager + ClusterIssuer `solace-lab-ca-issuer`
- trust-manager + Kyverno policy
  `inject-solace-lab-ca-trust-bundle` (mounts the CA bundle and
  sets `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` in every pod). Do
  NOT enable `samDeployment.customCA` -- it mounts over the same
  path and would conflict.
- Private registry at `registry.solace.lab` with Kyverno policy
  `inject-registry-pull-secret`; the values additionally list the
  secret in `global.imagePullSecrets` so the sam-doctor hook pod
  can pull.
- Keycloak at `auth.solace.lab` with the `solace-lab` realm

In addition, `start.sh` registers `sam.solace.lab` in CoreDNS
NodeHosts during deployment (and `stop.sh` removes it again) --
SAM self-calls its external URL during the OAuth flow.

Do not re-create any of these resources from this repository.
All Keycloak-side configuration this repo owns is scoped to the
`solace-agent-mesh` OIDC client plus `viewer`, `data_engineer`,
`power_user` groups and demo users within the `solace-lab` realm.

## Start and Stop

```bash
./scripts/setup-keycloak-client.sh  # create OIDC client first
./scripts/setup-keycloak-users.sh   # create groups and demo users
docker login registry.solace.lab    # once
./scripts/load-images.sh            # offline tarballs -> registry
./scripts/start.sh                  # helm install (local chart)
./scripts/rbac/apply-rbac.sh        # roles + claim mappings
./scripts/stop.sh                   # full teardown
```

## Secrets Handling

- Deployment-specific secrets (Keycloak OIDC client secret and
  LLM API key) live in `.env` (gitignored) and are injected via
  `--set` flags at deploy time. `start.sh` validates they are not
  left at `changeme`.
- `.env.example` is the checked-in template with placeholders.
- Non-sensitive demo-only values (session key, broker default
  password, DNS name, pull secret name) are kept in
  `local-k8s-values.yaml` for reproducibility.

## v2 Chart Gotchas

- The values schema is strict (`additionalProperties: false`) --
  unknown or v1-era keys fail the install.
- `global.imageRegistry` defaults to `gcr.io/gcp-maas-prod` and is
  prepended to EVERY image with a blank per-image registry. Keep
  it `""`; gwe/str carry `registry.solace.lab` per-image.
- Never blank `samDeployment.str.image.repository` -- it would
  silently inherit the gwe image and break tool execution.
- The seaweedfs tag must be pinned to `3.97` in TWO places
  (`samDeployment.s3Init.image.tag` and
  `persistence-layer.seaweedfs.image.tag`); the chart default
  `3.97-compliant` exists only in Solace's private registry.
- `global.persistence.namespaceId` also namespaces the broker
  topics -- kept at `sam-solace-lab` for continuity with v1.
- The `sam-doctor` pre-install hook tests broker/LLM/OIDC
  reachability; it runs warn-only via
  `samDoctor.failOnError: false`.
- The chart validates at install time that the ingress TLS secret
  exists -- `start.sh` applies and waits on the cert-manager
  Certificate before helm.

## RBAC (v2 model)

Helm values seed ONLY bootstrap admins
(`sam.authenticationRbac.users` -> `sam_admin@solace.lab` with the
YAML role `sam_admin`). Everything else is DB-managed and applied
post-install from `scripts/rbac/` via `sam config apply`:
roles `sam_user`, `viewer`, `data_engineer`, `power_user`, claim
mappings for the Keycloak groups, and default roles `[sam_user]`.

Scope grammar is v2 style `<category>:<resource>:<verb>` (e.g.
`agent:*:invoke`, `connector:_:create`, `deployment:_:read`).
Do NOT use v1 quickstart scopes (`artifact:read`,
`sam:connectors:*`) or v1 `agent:*:delegate` -- they are not part
of the v2 grammar. Claim mappings and default roles may only
reference DB-managed roles, never the YAML `sam_admin`.

## Key Files

- `local-k8s-values.yaml` -- Non-sensitive Helm values
  (safe to commit)
- `.env.example` -- Template for secrets and artifact paths
- `manifests/sam-tls-certificate.yaml` -- cert-manager
  Certificate for the ingress TLS secret
- `scripts/load-images.sh` -- Loads the offline image tarballs
  and pushes them to `registry.solace.lab`
- `scripts/start.sh` -- Sources `.env`, installs from
  `SAM_CHART_PATH`
- `scripts/stop.sh` -- Full teardown including Keycloak client
- `scripts/rbac/` -- Declarative RBAC (manifest + roles + claim
  mappings + `apply-rbac.sh`)
- `scripts/setup-keycloak-client.sh` / `setup-keycloak-users.sh`
  and their teardown counterparts -- Keycloak client, groups,
  demo users
- `scripts/agents/`, `scripts/models/` -- REST provisioning and
  model tuning written against the v1 platform API; unverified
  on v2 (v2 exposes similar endpoints, e.g.
  `/api/v1/platform/connectors`, but token handling may differ)

## References

- SAM v2 docs:
  <https://docs.solace.com/Agent-Mesh/Framework/get-started/agent-mesh-overview.htm>
- RBAC reference:
  <https://docs.solace.com/Agent-Mesh/Framework/reference/rbac-reference.htm>
- CLI reference:
  <https://docs.solace.com/Agent-Mesh/Framework/reference/cli.htm>
