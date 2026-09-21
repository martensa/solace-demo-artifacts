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

Deployed version: chart `solace-agent-mesh` 2.1.164, appVersion
2.348.22, str 1.64.0 (app and str are versioned independently).

The chart and images come from the offline SAM delivery package
and are NOT checked in. `.env` carries the local paths:
`SAM_CHART_PATH` (unpacked chart), `SAM_APP_IMAGE_TAR` /
`SAM_STR_IMAGE_TAR` (image tarballs for `load-images.sh`),
`SAM_CLI_PATH` / `SAM_CLI_TAR` (sam CLI; the 2.348.22 package
ships no CLI tarball, the CLI lives in `~/.local/bin/sam`).

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

Event-mesh entrypoint rules should set `defaultUserIdentity`
(e.g. `sam_admin@solace.lab`): without it, event-triggered tasks
run under the bare gateway identity and are invisible in the
Activities UI (and unattributed in chargeback). Verified
2026-08-03; the schema also offers `userIdentityExpression` for
per-message identity.

In addition, `start.sh` registers `sam.solace.lab` in CoreDNS
NodeHosts during deployment (and `stop.sh` removes it again) --
SAM self-calls its external URL during the OAuth flow.

Do not re-create any of these resources from this repository.
All Keycloak-side configuration this repo owns is scoped to the
`solace-agent-mesh` OIDC client plus the `admin`, `user`,
`viewer`, `data_engineer`, `power_user` and `sam_manager` groups
and their demo users within the `solace-lab` realm.

## Start and Stop

```bash
./scripts/setup-keycloak-client.sh  # OIDC client; writes the secret to .env
./scripts/setup-keycloak-users.sh   # create groups and demo users
docker login registry.solace.lab    # once
./scripts/load-images.sh            # offline tarballs -> registry
./scripts/start.sh                  # helm install, then (in a
                                    # terminal) browser login +
                                    # provision.sh
./scripts/provision.sh --login      # standalone / non-TTY: RBAC,
                                    # models, max_tokens, developer-mcp
./scripts/stop.sh                   # full teardown
./scripts/stop.sh --purge-images    # ... plus the SAM images
```

`provision.sh` runs, in order: `rbac/apply-rbac.sh`,
`models/apply-models.sh` (six extra aliases incl. `google gemini`),
`models/set-max-tokens.sh` (general/planning/report_gen, one awe
restart only if something changed) and
`entrypoints/apply-entrypoints.sh`. All idempotent. It needs a
`sam auth login` as `sam_admin`, which can only happen once the
platform is up -- a Claude session cannot do that browser login
(password entry), so ask the user to run
`sam auth login solace-lab --url https://sam.solace.lab` and then
run `./scripts/provision.sh` yourself.

Version upgrade (new delivery package): install the NEW sam CLI,
then run `./scripts/upgrade-preflight.sh --new <package-dir>`
first -- it decides whether `local-k8s-values.yaml` (sections
3/7) or any declarative package (section 8, `sam config plan`
with the new CLI) needs changes before anything is torn down.
The full ordered procedure (preflight, teardown, re-pin, load
images, install + provision, verify, purge the old images) is
the README's "Upgrade" section. Package directory names contain
spaces (2.348.22: a TRAILING space) -- always glob, and
version-specific (`~/Downloads/SAM*Enterprise*Update*2.348.22*`:
the previous package stays in ~/Downloads while `.env` points
into it), never type the name, and keep `.env` paths quoted.

This deployment is pure SAM INFRASTRUCTURE (platform, RBAC,
models, developer-mcp entrypoint, observability). It carries NO
demo content: demos live in their own top-level directories
(../sam-retail-ops-demo/, ../sam-manufacturing-ops-demo/), each
with its own core (domain connectors/skills/experts), overlay,
eval package and dashboard, installed/removed via idempotent
install.sh / uninstall.sh (--keep-core keeps a demo's core for
fast overlay switching; the demo install scripts also start the
host data stores postgres/pgadmin + demo mongo).

stop.sh destroys the platform DB and with it all DB-managed
content (RBAC, installed demos, developer-mcp, model tuning) --
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
- Chart 2.1.164 adds `sam.oauthProvider.claimKey` ->
  env `EXTERNAL_AUTH_CLAIM_KEY` (default `groups`): the OIDC
  claim the RBAC claim mappings match, now DEPLOYMENT-WIDE.
  Deliberately left unset -- `groups` is what the Keycloak group
  mapper emits. Nothing else changed in the values schema between
  2.0.23 and 2.1.164, and the subcharts (persistence-layer 1.10.0,
  sam-common 1.1.1) are unchanged. The CLI schema DID change with
  2.348.22: `rbacClaimMapping` lost `spec.claimKey` and
  `roleName` became `roleNames` (list) -- the helm-side preflight
  could not see that; preflight section 8 now can.
- Metrics: `environmentVariables.SAM_OBSERVABILITY_ENABLED: "true"`
  in the values switches on the env-gated `management_server`
  block that every baked config carries since 2.348.22. Do NOT
  re-introduce full-file config overlays: a second
  `management_server` key would break the config. The 2.225.14
  Helm post-renderer plugin `sam-observability` is gone.
- Rancher Desktop shares the Docker image store with k3s: the
  kubelet image GC deletes UNUSED images when the VM disk crosses
  85 % (seen on the 2.348.22 upgrade: str 1.50.3 vanished locally
  during start.sh). The registry copy is the only dependable
  fallback image.
- `ingress.annotations` is a FREE-FORM map in the schema. A
  values-schema checker that assumes a missing
  `additionalProperties` means "forbidden" will report every
  annotation as an unknown key -- the JSON Schema default is
  permissive.
- The `sam-doctor` pre-install hook tests broker/LLM/OIDC
  reachability; it runs warn-only via
  `samDoctor.failOnError: false`.
- The chart validates at install time that the ingress TLS secret
  exists -- `start.sh` applies and waits on the cert-manager
  Certificate before helm.
- STR restart vs connector tools -- SELF-HEALING since 2.348.22
  (verified 2026-09-21 with a scratch SQL connector): the restart
  still drops the dynamically registered tool package
  (`<subtype>_sql_query_<connector-id prefix>`, Mongo
  per-collection tools), and the first call after it gets "tool
  not in manifest" from str -- but awe now re-registers it via
  `init_request` and retries ("connector tool re-registered via
  init_request; retrying"): the call succeeds ~1 s later. The
  2.225.14 remedy (touch every connector config and re-apply) is
  no longer needed.
- Deleting a connector still leaves its tool subscription
  (`.../sam_remote_tool/invoke/<tool>_<id prefix>`) on
  `q/str/builtin-tools-worker` (re-verified on 2.348.22). Harmless
  (the id prefix is never reused); stop.sh drops the whole queue.
- The platform REST path for entrypoints was renamed in 2.348.22:
  `/api/v1/platform/gateways` -> `/api/v1/platform/entrypoints`
  and `/gatewayDeployments` -> `/entrypointDeployments` (same
  response shape, deploy body still `{gatewayId, action}`); the
  old paths return 404. The sam CLI already uses the new ones.
- Event-mesh entrypoint -> WORKFLOW target is STILL broken on
  2.348.22 (re-verified 2026-09-21, A2A sniff): with
  `targetWorkflowName: <config name>` the gateway publishes to
  `a2a/v1/agent/request/<config name>` (the workflow listens on
  `workflow_<uuid with _>`, so nobody picks it up; redelivery at
  the ack timeout) AND the message text is empty (promptTemplate
  is rendered for agent targets only). The runtime-name workaround
  still works: `targetWorkflowName: workflow_<uuid with _>` +
  `inputExpression: "input.payload"` -> the workflow gets the
  event JSON, runs, and successOutput (responseType full) carries
  the output_mapping as a data part. promptTemplate stays ignored
  for workflow targets even then.
- AI Builder with an EXISTING connector (2.225.14 "validation
  deadlock": the manifest validator demanded `connectors`, the
  config validator forbade it) -- resolved on 2.348.22 at the
  validation level: the wiring lives in the build MANIFEST
  (`connectors:`/`depends_on:` of the agent component), the agent
  config carries none, and both `validate_component_config` and
  `validate_build_manifest` pass. The Builder then stops at
  `request_build_activate`: with the default feature flag
  `builder_server_apply=false` the FRONTEND saves the components
  on the "Build & Activate" click and adds the connector ids from
  the manifest (`/api/v1/platform/builder/builds` is not even
  routed). That last step was not exercised headlessly.
- Builder Test engine WORKS on 2.348.22 (verified 2026-09-21 via
  the WebUI's API path: POST /api/v1/sessions {id} -> POST
  /api/v1/platform/builder/sessions/{id}/test-agent
  {componentName, componentKind} -> test session
  `{agentId: TEST_AGENT_INSTANCE_NAME, source: builder_test}` ->
  message:send "Create a test for me"). The 2.225.14 defect (the
  caller killed `generate_test_plan` after 30 s) is fixed:
  str 1.64.0 gives both test-harness tools 300 s (DATAGO-147065),
  and the new `tool_model_alias` (env `STR_TOOL_MODEL_ALIAS`,
  default `general`) makes the in-tool model operator-
  controllable. Quirk: the tool sends `temperature: 0.3`, Opus 4.8
  (via the LiteLLM proxy -> Bedrock) rejects it, and the PROXY
  takes ~84 s to return that 400. STR then drops the param and
  remembers it per policy key, so the FIRST test plan after every
  str start takes ~87 s, later ones ~4 s. If that first wait
  matters, set `STR_TOOL_MODEL_ALIAS: planning` (Haiku, accepts
  temperature) via `environmentVariables` -- not done, test plans
  stay on the general tier. Ephemeral test agents
  (`isEphemeral`, `expiresAt` +3 days, swept by gwe) delete
  cleanly via DELETE /api/v1/platform/agents/{id}; since 2.348.22
  an agent DELETE also removes its broker queue.
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
2.348.22 adds the BUILT-IN role `sam_manager` (platform-created,
`builtin=1`: all SAM administration except `rbac:*`); the Keycloak
group/user `sam_manager` maps to it (separation of duties -- only
`sam_admin` manages RBAC). Demo installs and provision.sh still
run as `sam_admin`: the sam CLI keeps one login per target, and
provision.sh applies RBAC.

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
  and pushes them to `registry.solace.lab`. The refs come from
  `local-k8s-values.yaml` (`samDeployment.gwe/str.image`), which
  is the single source of truth for the pinned versions; the
  script retags whatever name the tarball restores onto the pin
  and says so when the two differ.
- `scripts/purge-images.sh` -- Drops every tag of the SAM
  repositories that `local-k8s-values.yaml` does NOT pin, from
  the local Docker daemon and from `registry.solace.lab`
  (`--dry-run` to review). Registry deletes need
  `REGISTRY_STORAGE_DELETE_ENABLED=true` on the registry; without
  it the script reports HTTP 405 instead of failing. Registry
  credentials: inline `auth` in `~/.docker/config.json` OR the
  credential helper (`credsStore: osxkeychain` on this Mac).
  Only the two pinned repositories are touched -- the v1
  `solace-agent-mesh-enterprise` / `solace/solace-agent-mesh`
  images the lab agents run on are never purged.
- `scripts/upgrade-preflight.sh` -- Compares a new delivery with
  the deployed one. `--new` takes the delivery package
  directory (the chart is found in a subfolder such as `Charts/`,
  max three levels deep), a `.tgz` or an unpacked dir; archives
  are classified by CONTENT, so the image tarballs in `Images/`
  are not mistaken for charts. `--old` defaults to
  `SAM_CHART_PATH`. Prints the new image defaults to pin, the
  package's image/CLI tarballs as `.env` lines, checks
  every key of `local-k8s-values.yaml` against the new
  `values.schema.json` (strict schema: a renamed key fails the
  install), diffs the two schemas, flags chart defaults that
  changed under an override, runs `helm lint` + `helm
  template` with the real values, and (section 8) plans every
  declarative package (scripts/* and ../sam-*-demo/*) with the
  CLI provision.sh uses (`--skip-version-check --no-build`,
  read-only). The CLI validates the files only AFTER reaching the
  platform with a login -- so run it BEFORE the teardown, logged
  in, with the new CLI; "NOT VALIDATED" is not a pass.
- `scripts/start.sh` -- Sources `.env`, warns if the pinned
  images lost the metrics switch (`check-metrics-gate.sh`),
  installs from `SAM_CHART_PATH`, then runs `provision.sh --login`
  when stdin/stdout are a terminal (else prints that command)
- `scripts/provision.sh` -- DB-managed content after an install:
  RBAC -> models -> max_tokens -> developer-mcp (RBAC first as
  the auth smoke test; stops there on failure, later steps
  continue and report WARN/FAIL)
- `scripts/setup-keycloak-client.sh` -- creates the OIDC client
  and writes its secret into `.env` itself (re-run against an
  existing client re-syncs `.env`)
- `scripts/stop.sh` -- Full teardown. Beyond the release and the
  namespace it removes what lives OUTSIDE the namespace and would
  otherwise survive: the `sam-alerts` PrometheusRule and the
  `grafana-datasource-sam-platform-config` ConfigMap in
  `monitoring`, released PVs, the cached `sam` CLI
  (`scripts/lib/.cache/`) and its login cache, and the Keycloak
  client/groups/users.
  `--purge-images` also runs `purge-images.sh`.
- `scripts/lib/common.sh` -- shared helpers (.env loading, sam
  CLI resolution, SAM_AUTH_TOKEN export) sourced by the rbac,
  models and entrypoints scripts and the demo install/uninstall
  scripts
- `scripts/rbac/` -- Declarative RBAC (manifest + roles + claim
  mappings + `apply-rbac.sh`; default roles via one REST call)
- `scripts/setup-keycloak-client.sh` / `setup-keycloak-users.sh`
  and their teardown counterparts -- Keycloak client, groups,
  demo users
- `scripts/entrypoints/` -- Declarative package for the
  platform-level `developer-mcp` MCP entrypoint (infrastructure,
  used by the desktop wiring and Claude Code across all demos),
  applied by `apply-entrypoints.sh` (provision.sh step;
  `--probe-only` checks /gw/dev). NEVER `--prune` (demo
  event_mesh entrypoints are not managed here). A config change
  redeploys the entrypoint and invalidates its minted MCP tokens
  (clients re-auth automatically).
  NOTE: demo content (cores with domain connectors/skills/
  experts, overlays, eval packages, dashboards) lives in
  ../sam-retail-ops-demo/ and ../sam-manufacturing-ops-demo/,
  managed by their idempotent install.sh / uninstall.sh
  (NEVER `--prune` there either).
- `scripts/models/` -- `set-max-tokens.sh` patches
  `modelParams.max_tokens` via `sam api` (SAM_AUTH_TOKEN from the
  CLI login cache) on general/planning/report_gen (or one
  `--model-alias`), skips aliases already at the value, and
  restarts awe once only if something changed. Plus the
  declarative package for six additional aliases (`workflow` =
  Sonnet 5 for the incident merge, `reasoning` = DeepSeek V3.2,
  `coding` = Qwen3 Coder, `expert` = Opus 5, `fast` = Haiku 4.5,
  all via the LiteLLM proxy; `google gemini` = Gemini 3.6 Flash,
  provider `google_ai_studio`, DIRECT on the Gemini API with
  `GOOGLE_AI_STUDIO_API_KEY` -- alias name with a space, file
  `google-gemini.yaml`, the resolver matches by `name:`) applied
  by `apply-models.sh` (provision.sh step; `--probe-only` =
  upstream health check). The platform stores model API keys in
  plain text in the platform DB. Gotchas: the platform lowercases model
  aliases on create (declarative names must be lowercase); the
  Claude 5 family rejects temperature/top_p/top_k (HTTP 400); the
  proxy's azure-*/gemini-* routes have permanently broken backend
  credentials. The models and entrypoints tooling are v2-native
  and verified live.
- `scripts/observability/` -- `check-metrics-gate.sh` (start.sh
  guard: warns if a pinned image's baked configs no longer
  reference `SAM_OBSERVABILITY_ENABLED`) and
  `grant-grafana-platform-db.sh`. Metrics themselves come from
  the values switch (see v2 Chart Gotchas); `/metrics` rides the
  `--health-addr` port (gwe 9090, awe/str 8090). After
  simultaneous gwe+awe restarts the DB-managed agents may not
  load -- restart awe again AFTER gwe is ready.
  `manifests/observability/` holds metrics Services,
  ServiceMonitors, PrometheusRule (sam-alerts, ns monitoring) and
  the Grafana dashboards (ConfigMaps, label grafana_dashboard=1,
  folder annotation SAM). Token chargeback per user comes from
  the platform DB (`tasks` table, Grafana role grafana_ro), NOT
  from Prometheus (metrics carry no user identity). SAM emits NO
  OTel spans (verified 2.348.22: the gwe/awe/str binaries link
  only the OTel metric/log exporters, no trace SDK; Tempo lists
  only the broker). A2A traces come from broker tracing on the
  sam VPN (event-mesh repo);
  enabling a telemetry profile on a running broker needs a
  broker restart.
- `scripts/desktop/` -- wires the SAM desktop app (its platform
  runs unauthenticated on localhost:8800) to this deployment:
  `generate-manifest.sh` builds the connector's static tool
  manifest from the live mesh (`/api/v1/agentCards`; tool names
  `<card>_<skill name>`, where 2.348.22 shortens a UUID card
  `agent_<uuid>` / `workflow_<uuid>` to `<kind>_<last 8 hex>` --
  e.g. `agent_c985d10e_general`; 2.225.14 used the full card name.
  They embed platform-DB UUIDs -- regenerate after every rebuild),
  `connect.sh` applies both default models
  (`general` + `planning`) and the `mcp/remote` connector (gw/dev,
  OAuth discovery) to the desktop Orchestrator via
  `sam config apply`. Workflow MCP results carry only a
  completion status -- re-verified on 2.348.22 (2026-09-21, OAuth
  and tools/call against gw/dev): the result is exactly
  `Workflow "<display name>" completed successfully.`, none of the
  `output_mapping` fields cross MCP, while an agent tool returns
  the agent's answer. The tool descriptions steer report requests
  through the K8s Orchestrator tool instead.

## References

- SAM v2 docs:
  <https://docs.solace.com/Agent-Mesh/Framework/get-started/agent-mesh-overview.htm>
- RBAC reference:
  <https://docs.solace.com/Agent-Mesh/Framework/reference/rbac-reference.htm>
- CLI reference:
  <https://docs.solace.com/Agent-Mesh/Framework/reference/cli.htm>
