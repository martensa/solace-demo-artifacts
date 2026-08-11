# Event-Driven Retail Operations Demo (SAM v2)

20-minute live demo, layered as a removable overlay on top of
the base platform in `agent-mesh-deployment/`. Start with
[talk-track.md](talk-track.md) -- the single source of truth:
spoken script, click paths, pre-flight checklist, fallbacks,
known limits and Q&A prep.

## Install / remove

With the base platform running (one-click deployment plus
`sam auth login`, see `agent-mesh-deployment/README.md`):

```bash
./install.sh
```

Idempotent: starts the host data stores (postgres/pgadmin with
the `retail_*` databases seeded from `postgres/`, MongoDB incl.
first-run seed), applies the retail core package (`core/`), the
five model aliases, the demo mesh overlay, the eval package and
the demo dashboard. By default it leaves the
Retail POS Analyst REMOVED while the `retail-poslog` connector
stays pre-provisioned: the live Builder beat creates only the
agent binding it (one config, no connector sub-task -- fast and
reliable on stage); `--with-pos` keeps the agent for
rehearsals.

Only ONE demo overlay runs at a time: `install.sh` refuses to
install while another demo's entrypoint is on the platform
(pointing at its `uninstall.sh`), and stops any other demo's
mongo container occupying port 27017.

```bash
./uninstall.sh
```

### Script flags

`install.sh`:

- (no flag) -- clean state for the live demo: Retail POS
  Analyst absent, `retail-poslog` connector pre-provisioned
- `--with-pos` -- keep the POS analyst agent (rehearsals; skips
  the live Builder beat)

`uninstall.sh`:

- (no flag) -- removes the demo overlay AND the retail core
  (agents, connectors, skills), the eval experiments and
  dataset (INCLUDING their run history), the demo dashboard,
  and the `retail-pos-mongo` container INCLUDING its anonymous
  data volume
- `--keep-core` -- remove only the overlay; keep the core for
  fast re-install
- `--dry-run` -- preview everything without changing anything
- `--purge-data` -- additionally DROP the three `retail_*`
  postgres databases; combined with the default mongo removal
  this deletes the demo COMPLETELY, data and volumes included
  (a fresh `install.sh` re-seeds everything in seconds)

Always kept: the SAM infrastructure (models, RBAC,
developer-mcp, observability) and the shared postgres/pgadmin
host containers.

## Contents

- `talk-track.md` -- the complete demo script (English)
- `install.sh` / `uninstall.sh` -- demo lifecycle on top of the
  base platform (idempotent)
- `preflight.sh` -- automated Appendix A checklist with
  auto-fix; ends READY / NOT READY (run ~15 min before going
  live)
- `demo-links.sh` -- prints direct SAM UI links for the demo
  windows (workflow display-name links are stable; agent and
  connector links are resolved by ID via the platform API)
- `core/` -- the retail CORE package (`sam config apply`):
  CRM/OMS/PDM postgres connectors, schema skill bundles, three
  query expert agents, the Retail 360 Reporter and the
  retail-360-report workflow. Removed by uninstall.sh unless
  `--keep-core`
- `mesh/` -- declarative demo resources (`sam config apply`):
  Order Confirmation Clerk (fast tier), Order Incident Reporter
  (workflow tier), order-incident-report workflow, shop-events
  event-mesh entrypoint
- `fallback/` -- break-glass configs for the live Builder beat
  (POS analyst + retail-poslog connector; NEVER `--prune`)
- `eval/` -- dataset `retail-ops-questions` plus the
  `retail-ops-quality` gate and the `retail-ops-model-benchmark`
  (same agent pinned to three models via `spec.models`)
- `observability/` -- the "SAM Retail Ops Demo" Grafana
  dashboard (ConfigMap)
- `shop/index.html` -- the Acme online shop: publishes order
  events straight to the sam VPN via solclientjs
  (`ws://localhost:8008`) and displays agent responses live
- `postgres/` -- seed package for the `retail_crm`, `retail_oms`
  and `retail_pdm` databases in the host `postgres` container
  (`seed.sh` + pg_dump SQL files; idempotent, run by install.sh)
- `mongodb/` -- POSLOG store: `docker compose up -d` imports 57
  transactions -- the original blog artifact
  ([solace-sam-demos/sam-retail][repo], 20 receipts) plus the
  demo story transactions in the same document shape
  (read-only user `sam_ro` for the SAM connector)
- `slides/` -- the deck: lifecycle, platform architecture, the
  high-level POS scenario and the lifecycle mapping

[repo]: https://github.com/martensa/solace-sam-demos/tree/master/sam-retail
