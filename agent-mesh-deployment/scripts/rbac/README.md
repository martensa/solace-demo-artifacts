# RBAC Configuration (SAM v2)

Declarative RBAC for the SAM v2 deployment, applied post-install
with `sam config apply`. This ports the v1 Helm-values RBAC
(`customRoles`, `idpClaims`, `defaultRoles`) to the v2 model, where
Helm values only seed bootstrap admins and everything else is
DB-managed through the platform.

## Why this moved out of the Helm values

The v2 chart has no values for custom roles, claim mappings or
default roles. It renders exactly one YAML role (`sam_admin`,
scopes `*`) and the bootstrap admin users
(`sam.authenticationRbac.users`, here: `sam_admin@solace.lab`).
Claim mappings and default roles may only reference DB-managed
roles -- never YAML roles -- so all other roles are created here as
`rbacRole` resources.

## The v2 scope model

Scopes are `<category>:<resource>:<verb>` with three segments.
`*` globs a segment, `_` marks collection-level scopes without an
instance (for example `connector:_:create`). Built-in tool and
artifact operations are implied by the agent invoke scope, so v1
grants like `tool:basic:*` or `artifact:read` have no direct v2
counterpart.

Scope mapping from the v1 roles:

| v1 (Helm quickstart style)  | v2 (this directory)      |
|-----------------------------|--------------------------|
| `agent:*:delegate`          | `agent:*:invoke`         |
| `artifact:read` / `write`   | implied by agent invoke  |
| `tool:basic:*`, `tool:data:*` | implied by agent invoke |
| `sam:deployments:read`      | `deployment:_:read`      |
| `sam:connectors:read`       | `connector:*:read`       |
| `sam:connectors:create`     | `connector:_:create`     |
| `sam:connectors:*`          | `connector:*:*`          |
| `sam:agent_builder:read`    | `agent_builder:*:read`   |
| (not available in v1)       | `workflow:*:invoke`      |

## Files

- `manifest.yaml` -- the `sam config` manifest (target
  `https://sam.solace.lab`, OAuth token cache).
- `rbac/roles/` -- one `rbacRole` per file:
  - `sam_user` -- basic interactive access (`agent:*:invoke`).
    DB-managed replacement for the v1 built-in of the same name.
  - `viewer` -- passive read-only (deployments, connectors, tool
    catalog); deliberately no invoke scope.
  - `data_engineer` -- agent and workflow invoke plus connector
    read/create.
  - `power_user` -- invoke, workflows, agent-builder read, full
    connector management, deployment read.
- `rbac/claim-mappings/` -- one `rbacClaimMapping` per Keycloak
  group (`user`, `viewer`, `data_engineer`, `power_user`). The
  provider name is `azure` -- the platform's generic OIDC catalog
  entry, which is what the Helm chart wires Keycloak into. Claim
  values are plain group names because the Keycloak group mapper
  uses `full.path=false`.
- `apply-rbac.sh` -- plan + apply + default roles.

## The admin group

There is no claim mapping for the Keycloak `admin` group: claim
mappings cannot reference the YAML-managed `sam_admin` role. The
admin grant comes from the Helm values instead
(`sam.authenticationRbac.users` seeds `sam_admin@solace.lab` with
the `sam_admin` role).

## Default roles

v1 parity keeps `sam_user` as the fallback for authenticated users
without a matching group (for example the realm accounts `admin`
and `user`). Per the SAM RBAC reference, default roles are a
fallback, not an addition: they apply only to identities with no
assignment from file, claim mapping or database -- so they do not
stack onto group-mapped users such as `viewer`. There is no
declarative kind for default roles; `apply-rbac.sh` sets them
through the platform REST API
(`PUT /api/v1/platform/rbac/defaultRoles`) after the roles exist.

## Usage

```bash
# one-time: log in as the bootstrap admin (browser flow)
sam auth login solace-lab --url https://sam.solace.lab

./apply-rbac.sh
```

The sam CLI is resolved by `../lib/common.sh`: `SAM_CLI_PATH`
from `.env`, then the PATH, then auto-extracted from
`SAM_CLI_TAR` into `../lib/.cache/` (gitignored). The CLI ships
in the SAM delivery package as
`solace-agent-mesh-<version>-cli-<os>-<arch>.tar.gz`.

Re-running is safe: `sam config apply` reconciles create/update;
deletions require `--prune` and are not part of the push-button
flow.
