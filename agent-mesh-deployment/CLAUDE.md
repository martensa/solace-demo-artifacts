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
docker start postgres pgadmin       # retail demo DBs (host)
(cd scripts/agents && ./create.sh --deploy)  # retail demo
(cd scripts/models && ./set-max-tokens.sh)   # max_tokens 16384
# additional models (workflow/reasoning/coding/expert/fast) are
# applied by start.sh; standalone: scripts/models/apply-models.sh
./scripts/stop.sh                   # full teardown
```

stop.sh destroys the platform DB and with it all DB-managed
content (RBAC, agents, workflow, MCP entrypoint, model tuning) --
the README's "Rebuilding after teardown" section documents the
re-provisioning order.

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
- An STR restart LOSES ALL dynamically registered connector
  tool packages -- MongoDB per-collection tools
  (`<collection>_mongo_query_<uuid>`) AND the SQL connector
  tools (`<name>_sql_query_<uuid>`): the durable topic
  subscription survives, but invokes fail with "tool not in
  manifest" and the agent reports the data source as offline.
  The package is pushed to STR on connector CREATE and UPDATE;
  an agent redeploy does NOT restore it (all verified
  2026-08-03). Remedy: touch each connector config (e.g. a
  one-word description tweak) and `sam config apply` -- the
  update re-pushes the package, UUIDs stay stable. Check every
  connector-backed agent after any STR restart.
- The Builder Test engine is broken in 2.225.14: its
  `generate_test_plan` str tool is killed at a hard 30 s
  (caller-side `timeout_seconds` default; the skill manifest's
  90 s is ignored) while its LLM call needs ~106 s on Opus -- and
  the model it uses is NOT operator-controllable (env in
  str/awe/gwe, DB `planning` alias and the ephemeral test
  agent's binding were all switched to Haiku and verified
  ineffective via bifrost debug logs). Vendor ticket material.
  Harmless leftovers: DB alias `planning` = Haiku, and a
  platform-DB trigger `ephemeral_agent_default_model` binding
  ephemeral test agents to `fast` (their chat then runs Haiku).
  Both vanish with stop.sh.
- `sam config apply`'s deploy phase only fires for resources whose
  config CHANGED in that apply: re-running `--deploy` over an
  unchanged undeployed resource is a silent no-op (bump a config
  field, e.g. the workflow appConfig version, to force it).

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
- `scripts/lib/common.sh` -- shared helpers (.env loading, sam
  CLI resolution, SAM_AUTH_TOKEN export) sourced by the rbac,
  agents and models scripts
- `scripts/rbac/` -- Declarative RBAC (manifest + roles + claim
  mappings + `apply-rbac.sh`; default roles via one REST call)
- `scripts/setup-keycloak-client.sh` / `setup-keycloak-users.sh`
  and their teardown counterparts -- Keycloak client, groups,
  demo users
- `scripts/agents/` -- Declarative retail demo provisioning
  (connectors, schema skills, agents, workflow, MCP entrypoint)
  applied via `sam config plan/apply` by `create.sh`; NOT
  deployed by default (`--deploy` to deploy; NEVER `--prune`)
- `scripts/models/` -- `set-max-tokens.sh` patches
  `modelParams.max_tokens` via `sam api` (SAM_AUTH_TOKEN from the
  CLI login cache) and restarts the awe deployment. Plus the
  declarative package for five additional aliases (`workflow` =
  Sonnet 5 for the incident merge, `reasoning` = DeepSeek V3.2,
  `coding` = Qwen3 Coder, `expert` = Opus 5, `fast` = Haiku 4.5)
  applied by `apply-models.sh` (start.sh hook; `--probe-only` =
  upstream health check). Gotchas: the platform lowercases model
  aliases on create (declarative names must be lowercase); the
  Claude 5 family rejects temperature/top_p/top_k (HTTP 400); the
  proxy's azure-*/gemini-* routes have permanently broken backend
  credentials. Both agents and models tooling are v2-native and
  verified live.
- `scripts/observability/` -- overlays the image-baked component
  configs with a `management_server` block (metrics) via a Helm 4
  postrenderer/v1 plugin + kustomize (configMapGenerator hash =
  auto-rollout). Gotchas: the block only works in the MAIN config
  (extra `--config` files reject root keys: "expected YAML
  list"); `/metrics` rides the `--health-addr` port (gwe 9090,
  awe/str 8090); full-file overlays are drift-checked against the
  delivery images by start.sh (`check-config-drift.sh`, re-base
  on new delivery). After simultaneous gwe+awe restarts the
  DB-managed agents may not load -- restart awe again AFTER gwe
  is ready. `manifests/observability/` holds metrics Services,
  ServiceMonitors, PrometheusRule (sam-alerts, ns monitoring) and
  the Grafana dashboards (ConfigMaps, label grafana_dashboard=1,
  folder annotation SAM). Token chargeback per user comes from
  the platform DB (`tasks` table, Grafana role grafana_ro), NOT
  from Prometheus (metrics carry no user identity). A2A traces
  come from broker tracing on the sam VPN (event-mesh repo);
  enabling a telemetry profile on a running broker needs a
  broker restart.
- `scripts/desktop/` -- wires the SAM desktop app (its platform
  runs unauthenticated on localhost:8800) to this deployment:
  `generate-manifest.sh` builds the connector's static tool
  manifest from the live mesh (`/api/v1/agentCards`; tool names
  `<card>_<skill name>` embed platform-DB UUIDs -- regenerate
  after every rebuild), `connect.sh` applies both default models
  (`general` + `planning`) and the `mcp/remote` connector (gw/dev,
  OAuth discovery) to the desktop Orchestrator via
  `sam config apply`. Workflow MCP results carry only a
  completion status in 2.225.14 -- the tool descriptions steer
  report requests through the K8s Orchestrator tool instead.

## References

- SAM v2 docs:
  <https://docs.solace.com/Agent-Mesh/Framework/get-started/agent-mesh-overview.htm>
- RBAC reference:
  <https://docs.solace.com/Agent-Mesh/Framework/reference/rbac-reference.htm>
- CLI reference:
  <https://docs.solace.com/Agent-Mesh/Framework/reference/cli.htm>
