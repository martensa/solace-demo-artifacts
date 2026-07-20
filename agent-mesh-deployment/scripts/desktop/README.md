# Desktop App to K8s Mesh (MCP)

Connects the SAM desktop app ("Solace Agent Mesh.app", the
encapsulated trial environment) to the local Kubernetes
deployment -- over the same MCP entrypoint Claude Code uses
(`https://sam.solace.lab/gw/dev`). The desktop stays fully local
(embedded broker, SQLite); its Orchestrator gains every K8s mesh
agent as a callable MCP tool.

## What connect.sh applies

Against the desktop app's local platform (`http://localhost:8800`,
no auth), via `sam config plan/apply`:

- `models/general.yaml` -- configures the desktop's `general`
  model alias with the lab LiteLLM proxy. The API key resolves
  from the repo `.env` (`LLM_SERVICE_API_KEY`) through the CLI's
  nearest-ancestor `.env` auto-loading; `max_tokens: 16384`
  matches the K8s-side tuning.
- `connectors/SAM K8s Mesh.yaml` -- `mcp/remote` connector to
  `https://sam.solace.lab/gw/dev` (Streamable HTTP,
  `auth_type: oauth` with `auth_oauth_mode: discovery` -- the
  same OAuth 2.1 flow Claude Code uses).
- `agents/Orchestrator.yaml` -- the desktop's built-in
  Orchestrator (pulled via `sam config pull`) extended with the
  connector.

## Usage

```bash
open -a "Solace Agent Mesh"   # start the desktop app
./connect.sh                  # idempotent plan + apply
```

Then chat with the Orchestrator in the app: on the first K8s tool
call the app runs the Keycloak OAuth login (use a demo user with
agent invoke scopes, e.g. `sam_admin` or `power_user`). The K8s
agents appear as tools named `<agent>_<skill>`, RBAC-filtered per
the logged-in user -- for example
`retail_crm_query_expert_query_retail_crm`.

## Notes

- TLS: the desktop app is a Go binary and trusts the macOS
  keychain, where the lab CA is installed -- no extra CA
  configuration (unlike Node-based clients).
- The desktop keeps its own encapsulated runtime; only the tool
  calls go to the K8s mesh. Rebuilding the K8s deployment does
  not require re-running connect.sh (the entrypoint URL stays
  stable), but a new OAuth login may be needed after the MCP
  entrypoint restarts.
- Re-running `connect.sh` is safe (reconciles). NEVER pass
  `--prune` -- the manifest does not manage the desktop's sample
  resources.
- Reset: delete the connector in the desktop app's Connectors UI
  and remove it from the Orchestrator, or wipe the desktop state
  (`~/Library/Application Support/sam/data`).
