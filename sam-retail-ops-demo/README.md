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

Idempotent: starts the host data stores (postgres/pgadmin,
MongoDB incl. first-run seed), applies the retail core package,
the five model aliases, the demo mesh overlay, the eval package
and the demo dashboard. By default it leaves the Retail POS
Analyst REMOVED (the live Builder beat creates it on stage);
`--with-pos` keeps it for rehearsals.

```bash
./uninstall.sh
```

Removes the demo's platform resources (incl. the eval
experiments and their run history) and the demo dashboard;
`--dry-run` previews, `--purge-data` also removes the MongoDB
container and volume. The base platform, retail core, models
and RBAC stay -- ready for a different demo overlay.

## Contents

- `talk-track.md` -- the complete demo script (English)
- `install.sh` / `uninstall.sh` -- demo lifecycle on top of the
  base platform (idempotent)
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
- `mongodb/` -- POSLOG store: `docker compose up -d` imports 57
  transactions -- the original blog artifact
  ([solace-sam-demos/sam-retail][repo], 20 receipts) plus the
  demo story transactions in the same document shape
  (read-only user `sam_ro` for the SAM connector)
- `slides/` -- the deck: lifecycle, platform architecture, the
  high-level POS scenario and the lifecycle mapping

[repo]: https://github.com/martensa/solace-sam-demos/tree/master/sam-retail
