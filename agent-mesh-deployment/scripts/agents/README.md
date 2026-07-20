# Retail Demo Provisioning (SAM v2)

Declarative provisioning of the retail demo -- connectors, skill
bundles, agents, a multi-agent workflow and an MCP entrypoint --
via the sam CLI (`sam config plan/apply`). No REST calls, no
tokens from the browser, no ID handling -- everything is
referenced by name and reconciled idempotently.

## Files

- `manifest.yaml` -- the `sam config` manifest (target
  `https://sam.solace.lab`, DB credential variables, resource
  lists).
- `connectors/` -- one `kind: connector` (sql/postgres) per
  retail database (CRM, OMS, PDM). Credentials come from the
  `${RETAIL_DB_USERNAME}` / `${RETAIL_DB_PASSWORD}` variables.
- `skills/` -- one instruction-only skill BUNDLE per database
  (`retail-*-schema`): `SKILL.md` documents the exact table,
  columns, types and query pitfalls (money casts, OMS line-item
  grain); `references/schema.md` adds value domains and example
  queries. Agents load these on demand before writing SQL.
- `agents/` -- one `kind: agent` per query expert plus the
  `Retail 360 Reporter` synthesis agent. Each query expert
  references by name: the `general` model alias, the built-in
  `data_analysis` and `builtin_artifact_tools` toolsets, its
  connector, its schema skill (`skillRefs`), and declares an
  inline agent-card skill.
- `workflows/` -- `retail-360-report`: fans a question out to
  the three query experts in parallel and merges their findings
  via the reporter agent.
- `entrypoints/` -- `developer-mcp`: exposes the agents as MCP
  tools at `https://sam.solace.lab/gw/dev/`.
- `create.sh` -- thin wrapper: plan, then apply.

## What each agent gets

- **Connector** (`spec.connectors`): provides the
  `execute_sql_query` tool against the live postgres database.
- **`data_analysis` toolset** (built-in, referenced by name):
  SQL on result artifacts (`create_sqlite_db`,
  `query_data_with_sql`) and Plotly chart generation
  (`create_chart_from_plotly_config`) -- the system prompts
  instruct the agents to use these for follow-up analysis and
  visualizations instead of re-querying the database.
- **`builtin_artifact_tools` toolset**: list/load artifacts.
- **Schema skill bundle** (`spec.skillRefs`): the agent loads its
  `retail-*-schema` skill before writing SQL -- exact table and
  column names, data-type gotchas (postgres `money` casts, text
  ranges) and, for OMS, the line-item-grain aggregation rules
  that prevent double counting.
- **Inline skill** (`spec.skills`): an agent-card capability
  advertisement (`{id, name, description}`) used for discovery,
  routing and MCP tool naming.
- **Agent card welcome** with click-to-run suggestions
  (`additionalConfigurations.agentCard.welcome`).

## Workflow: retail-360-report

Four nodes: `crm`, `oms`, `pdm` run in parallel (no
`depends_on` between them), `report` (the Retail 360 Reporter)
merges their outputs. Input wiring uses
`{{workflow.input.text}}` and `{{<node>.output}}` templates;
`output_mapping` returns the report. NOTE: text input delegated
over A2A arrives under the key `text` (verified in the awe log:
`inputKeys: ["text"]`) -- `{{workflow.input.message}}` stays
an unresolved placeholder.

Triggering (2.225.14): the WebUI chat picker lists agents only
(workflow cards are filtered out); trigger the workflow by asking
the Orchestrator to delegate to it, e.g. "Delegiere diese Aufgabe
an den Workflow 'Retail 360 Report': ...". The first cold run can
exceed the Orchestrator's delegation timeout -- it retries
automatically. RBAC: callers need `workflow:*:invoke` AND
`agent:*:invoke` -- every node hop is authorized against the
caller (`power_user` and `data_engineer` have both; `sam_user`
and `viewer` do not).

Known WebUI bug (2.225.14): the Builder's workflow list links by
the platform name, but the detail page resolves the MESH card
name -- clicking a CLI-created workflow shows "Workflow not
found". Workaround: open the card-name URL directly, e.g.
`https://sam.solace.lab/#/agents/workflows/workflow_<uuid>` with
the workflow's UUID in underscore form (get the UUID from
`sam api /api/v1/platform/workflows`).

## MCP entrypoint: developer-mcp

Serves MCP (Streamable HTTP) at `https://sam.solace.lab/gw/dev/`
on the same host as the WebUI. One MCP tool per agent-card skill,
named `<agent>_<skill>` (for example
`retail_crm_query_expert_query_retail_crm`).

ALL mesh agents are exposed (`includeTools` is empty): the retail
experts, the Retail 360 Reporter, Orchestrator, Builder and the
external agents. Narrow the surface with `includeTools` patterns
(matched against agent, skill and tool names; exact or regex) if
needed.

Auth is the cluster OIDC (Keycloak): OAuth 2.1 authorization
code with PKCE and dynamic client registration -- clients
discover everything from the 401 challenge. With RBAC on, `tools/list` is
filtered to the caller's `agent:<name>:invoke` scopes.

Connect from Claude Code:

```bash
claude mcp add --transport http sam-lab https://sam.solace.lab/gw/dev
```

Node-based clients (Claude Code included) do not use the macOS
keychain, so the lab CA must be provided explicitly, e.g. in
`~/.zshrc`:

```bash
export NODE_EXTRA_CA_CERTS="$HOME/.solace-lab/ca-bundle.crt"
```

(Bundle exported from the cluster ConfigMap
`solace-lab-ca-trust-bundle`.)

Notes: entrypoint tokens are minted in-memory per entrypoint --
a restart invalidates them (clients re-auth silently via refresh
token). Workflows are not exposed over MCP in 2.225.14; route via
an agent if needed.

## Prerequisites

- The sam CLI (resolved by `../lib/common.sh`: `SAM_CLI_PATH`,
  then PATH, then auto-extract from `SAM_CLI_TAR`) and a login as
  a user with agent_builder + connector scopes:

  ```bash
  sam auth login solace-lab --url https://sam.solace.lab
  ```

- The retail demo databases: a standalone postgres docker
  container on the HOST (containers `postgres` + `pgadmin`,
  managed outside this repo) serving `retail_crm`, `retail_oms`
  and `retail_pdm` on port 5432. The connectors reach it via
  `host.docker.internal:5432`. It stays `Exited` after host
  restarts -- start it with `docker start postgres pgadmin`.

## CLI usage

Run from this directory:

```bash
# Create/update connectors + agents; agents stay NOT deployed
./create.sh

# Same, and deploy the agents
./create.sh --deploy

# Plan only, change nothing
./create.sh --dry-run

# Different DB credentials (defaults: postgres/postgres)
RETAIL_DB_PASSWORD='secret' ./create.sh
```

Re-running is safe: `sam config apply` reconciles creates and
updates. Resources are created undeployed by default
(`--no-deploy`); `--deploy` runs the deployment phase for the
`deploy: true` resources.

CAUTION (2.225.14): the deploy phase only fires for resources
whose config CHANGED in that apply. After a create-only run,
re-running `--deploy` over unchanged resources is a silent no-op
-- bump any config field (e.g. the workflow `appConfig.version`)
to force the deploy phase for that resource.

## Notes

- NEVER pass `--prune` here: the platform hosts agents this
  manifest does not manage (for example the built-in
  Orchestrator). The plan output lists them as `delete`
  proposals; without `--prune` the apply skips them.
- Adding another agent: add `connectors/<name>.yaml`,
  `agents/<name>.yaml` and optionally `skills/<name>/SKILL.md`,
  then list the names in `manifest.yaml`.
- Changing a shared skill redeploys every agent bound to it;
  unchanged skills are hash-diffed and skipped.
- Secrets: `${VAR}` placeholders resolve at plan/apply time from
  the manifest `variables` block, the process environment, or a
  `.env` file; the platform stores the resolved value.
