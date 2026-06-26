# Agent and Connector Provisioning

Automated provisioning of Solace Agent Mesh (SAM) connectors and agents
through the SAM Platform REST API. The `create.sh` script creates the
connectors and agents from the JSON definitions in this directory.

It creates configuration only. Deploying each agent is a separate step; the
script prints ready-to-run deploy commands when it finishes.

## Files

- `create.sh` -- provisioning script (idempotent for connectors).
- `agent-retail_crm_query_expert.json` -- Retail CRM agent definition.
- `agent-retail_oms_query_expert.json` -- Retail OMS agent definition.
- `agent-retail_pdm_query_expert.json` -- Retail PDM agent definition.
- `connector-retail_crm_db.json` -- Retail CRM DB connector definition.
- `connector-retail_oms_db.json` -- Retail OMS DB connector definition.
- `connector-retail_pdm_db.json` -- Retail PDM DB connector definition.

Each agent is paired with its connector in the `PAIRS` list at the top of
`create.sh`.

## Prerequisites

- `curl` and `jq` on the PATH.
- A logged-in SAM session in Chrome (for automatic token detection), or a
  token passed explicitly (see below).

## What it does

For each agent and connector pair, the script:

1. Resolves the model id dynamically from its alias (default `general`).
2. Ensures the connector exists, matched by name. It is reused if present,
   otherwise created from the connector JSON.
3. Injects the resolved model id and connector id into the agent payload.
4. Creates the agent (configuration only, not deployed).

No ids are hard-coded, so the script runs unchanged in any SAM environment.

## CLI usage

Run the script from this directory:

```bash
# Auto-detect the token from Chrome, then create connectors + agents
./create.sh

# Pass the token explicitly (also: --token)
./create.sh -t '<sam_access_token>'

# Provide the token through the environment
SAM_TOKEN='<sam_access_token>' ./create.sh

# Resolve everything and report what would happen; create nothing
./create.sh --dry-run

# Print usage (also: -h)
./create.sh --help
```

Token resolution order: `-t/--token`, then `SAM_TOKEN`, then Chrome
localStorage.

### Environment variables

- `SAM_BASE` -- API base URL (default `https://sam.solace.lab`).
- `MODEL_ALIAS` -- model alias to resolve (default `general`).
- `DB_USERNAME` -- DB user, used only when a connector is created
  (default `postgres`).
- `DB_PASSWORD` -- DB password, used only when a connector is created
  (default `postgres`).

Example, creating connectors with a different password:

```bash
DB_PASSWORD='secret' ./create.sh
```

## Getting the token

The script reads the token automatically from Chrome. To pass it manually,
open the DevTools console on a logged-in SAM tab and run:

```js
copy(localStorage.getItem('sam_access_token'))
```

The token is short-lived (about one hour).

## Deploying

`create.sh` creates configuration only. When it finishes it prints one deploy
command per agent. Run those to roll the agents out, or deploy them later from
the WebUI.

## Adding another agent

1. Add an `agent-*.json` and a `connector-*.json` to this directory.
2. Append one line to the `PAIRS` list in `create.sh`.

No other change is needed.

## Notes

- Connector matching is by name. An existing connector is reused as-is and is
  not updated to match the JSON.
- Agent names are not unique, so a second run creates duplicate agents.
