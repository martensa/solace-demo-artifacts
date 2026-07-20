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
`{{workflow.input.message}}` and `{{<node>.output}}` templates;
`output_mapping` returns the report.

Once deployed, the workflow is addressable like an agent (chat,
delegation). RBAC: callers need `workflow:*:invoke` AND
`agent:*:invoke` -- every node hop is authorized against the
caller (the `power_user` role has both; `sam_user` does not).

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

Notes: entrypoint tokens are minted in-memory per entrypoint --
a restart invalidates them (clients re-auth silently via refresh
token). Workflows are not exposed over MCP in 2.225.14; route via
an agent if needed.

## Prerequisites

- The sam CLI (see `../rbac/README.md` for resolution order) and
  a login as a user with agent_builder + connector scopes:

  ```bash
  sam auth login solace-lab --url https://sam.solace.lab
  ```

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
updates. Agents are created undeployed by default (`--no-deploy`);
`--deploy` runs the deployment phase for the `deploy: true`
agents.

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
