# Agent and Connector Provisioning (SAM v2)

Declarative provisioning of the retail demo agents and their
postgres connectors via the sam CLI (`sam config plan/apply`).
No REST calls, no tokens from the browser, no ID handling --
everything is referenced by name and reconciled idempotently.

## Files

- `manifest.yaml` -- the `sam config` manifest (target
  `https://sam.solace.lab`, DB credential variables, resource
  lists).
- `connectors/` -- one `kind: connector` (sql/postgres) per
  retail database (CRM, OMS, PDM). Credentials come from the
  `${RETAIL_DB_USERNAME}` / `${RETAIL_DB_PASSWORD}` variables.
- `agents/` -- one `kind: agent` per query expert. Each agent
  references by name: the `general` model alias, the built-in
  `data_analysis` and `builtin_artifact_tools` toolsets, its
  connector, and declares an inline agent-card skill.
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
- **Inline skill** (`spec.skills`): an agent-card capability
  advertisement (`{id, name, description}`) used for discovery
  and routing. These are metadata-only ("instruction-only") --
  loadable skill bundles (SKILL.md packages) would go into
  `spec.skillRefs` instead and are not needed here.
- **Agent card welcome** with click-to-run suggestions
  (`additionalConfigurations.agentCard.welcome`).

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
- Adding another agent: add `connectors/<name>.yaml` and
  `agents/<name>.yaml`, then list both names in `manifest.yaml`.
- Secrets: `${VAR}` placeholders resolve at plan/apply time from
  the manifest `variables` block, the process environment, or a
  `.env` file; the platform stores the resolved value.
