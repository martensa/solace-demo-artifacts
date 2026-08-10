# Platform Entrypoints (SAM v2)

Declarative provisioning of the platform-level entrypoints --
currently the `developer-mcp` MCP endpoint. This is SAM
INFRASTRUCTURE, not demo content: the desktop-app wiring
(`../desktop/`) and MCP clients such as Claude Code use it
regardless of which demo overlay is installed. Demo event-mesh
entrypoints (shop-events, plant-events) live in their demo
directories instead.

Applied automatically by `start.sh` after the model aliases;
standalone:

```bash
./apply-entrypoints.sh               # apply + probe /gw/dev
./apply-entrypoints.sh --probe-only  # pre-flight reachability
```

NOTE: a config change redeploys the entrypoint and invalidates
its in-memory minted MCP tokens -- connected clients re-auth via
refresh token automatically.

## MCP entrypoint: developer-mcp

Serves MCP (Streamable HTTP) at `https://sam.solace.lab/gw/dev/`
on the same host as the WebUI. One MCP tool per agent-card skill,
named `<card>_<skill name>` (both sanitized: lowercase,
non-alphanumerics to `_`; the suffix comes from the skill NAME,
not the skill id). DB-managed agents and workflows carry their
UUID instance name as card name -- for example
`agent_<uuid>_query_retail_crm` -- so tool names change with
every platform rebuild.

ALL mesh agents are exposed (`includeTools` is empty): the
Orchestrator, the Builder, whatever demo experts are currently
installed and the external agents. Narrow the surface with
`includeTools` patterns (matched against agent, skill and tool
names; exact or regex) if needed.

Auth is the cluster OIDC (Keycloak): OAuth 2.1 authorization
code with PKCE and dynamic client registration -- clients
discover everything from the 401 challenge. With RBAC on,
`tools/list` is filtered to the caller's `agent:<name>:invoke`
scopes.

## Connecting Claude Code

1. Provide the lab CA: Node-based clients (Claude Code included)
   do not use the macOS keychain, so export the trust bundle once
   and reference it in `~/.zshrc`:

   ```bash
   mkdir -p ~/.solace-lab
   kubectl get configmap solace-lab-ca-trust-bundle -n default \
     -o jsonpath='{.data.ca-certificates\.crt}' \
     > ~/.solace-lab/ca-bundle.crt
   echo 'export NODE_EXTRA_CA_CERTS="$HOME/.solace-lab/ca-bundle.crt"' \
     >> ~/.zshrc
   ```

2. Register the MCP server (new terminal, so the env var is set):

   ```bash
   claude mcp add --transport http sam-lab https://sam.solace.lab/gw/dev
   ```

3. In Claude Code run `/mcp`, select `sam-lab` and choose
   Authenticate -- the browser opens the Keycloak login (use a
   demo user with agent invoke scopes, e.g. `sam_admin` or
   `power_user`). After the login the agent tools appear and can
   be used directly in chat.

Notes: entrypoint tokens are minted in-memory per entrypoint --
a restart invalidates them (clients re-auth silently via refresh
token). Deployed workflows ARE exposed as MCP tools (named
`workflow_<uuid>_<skill name>`, verified end-to-end); the tool's
`message` argument lands in `{{workflow.input.text}}`.

The loopback redirect paths for Claude Code
(`/callback`), MCP Inspector (`/oauth/callback`) and the SAM
desktop app (`/api/v1/auth/tool/callback`) are allowlisted in
`entrypoints/developer-mcp.yaml`.
