# Event-Driven Manufacturing Operations Demo (SAM v2)

*The Line Never Stops.* 20-minute live demo, layered as a
removable overlay on top of the base platform in
`agent-mesh-deployment/`. Manufacturing sibling of
`sam-retail-ops-demo/` -- same AI Worker Lifecycle dramaturgy
(hire, onboard, teamwork, improve), new stage: Acme
Manufacturing, two divisions (power tools and automotive
components), two plants, and TWO event-driven movements from one
click:

1. **React** -- an end-of-line failure at Plant 2 (Graz)
   triggers a quality incident analysis. Root cause:
   ECO-2025-118 (new HD-22 clutch disc + raised torque spec)
   was never acknowledged in Graz -- the part arrived, the
   master data did not.
2. **Prevent** -- the same ECO ramped HD-22 consumption at
   Plant 1 (Hamburg) past the old planning parameters. A stock
   threshold event fires and a replenishment recommendation
   lands before the line stops.

Start with [talk-track.md](talk-track.md) -- the demo script
(v0.1 skeleton; structure and beats final, SAY blocks not yet
rehearsal-hardened).

## Install / remove

With the base platform running (one-click deployment plus
`sam auth login`, see `agent-mesh-deployment/README.md`):

```bash
./install.sh
```

Idempotent: starts the host data stores (postgres/pgadmin with
the four seeded `mfg_*` databases, MongoDB `mfg-plant-mongo` on
port 27017 incl. first-run seed), applies the manufacturing core
package (`core/`), the five model aliases, the demo mesh
overlay, the eval package and the demo dashboard. By default it
leaves the Shop Floor Analyst REMOVED (the live Builder beat
creates it on stage); `--with-analyst` keeps it for rehearsals.

```bash
./uninstall.sh
```

Removes the demo's platform resources (overlay AND the
manufacturing core, incl. the eval experiments and their run
history), the demo dashboard and the MongoDB container with its
anonymous volume (a fresh `install.sh` re-seeds it in seconds);
`--keep-core` keeps the core for fast switching between demo
overlays, `--dry-run` previews. The SAM infrastructure (models,
RBAC, developer-mcp, observability) and the shared
postgres/pgadmin containers stay -- ready for a different demo.
The retail and manufacturing demos share the standard mongo
port 27017: each demo's install.sh stops the other demo's mongo
container automatically; the postgres databases coexist without
conflict.

## Contents

- `talk-track.md` -- the demo script (English)
- `install.sh` / `uninstall.sh` -- demo lifecycle on top of the
  base platform (idempotent)
- `core/` -- the manufacturing CORE package (`sam config
  apply`): Acme CRM/OMS/PDM/SCM postgres connectors, schema
  skill bundles, four query expert agents. Removed by
  uninstall.sh unless `--keep-core`; the retail analog is
  `sam-retail-ops-demo/core/`
- `mesh/` -- declarative demo resources (`sam config apply`):
  Production Confirmation Clerk (fast tier), Quality Incident
  Reporter + Supply Chain Watcher (workflow tier),
  quality-incident-report + supply-replenishment workflows,
  plant-events event-mesh entrypoint (three rules: released ->
  clerk, eol-failed -> incident, threshold-crossed ->
  replenishment)
- `fallback/` -- break-glass configs for the live Builder beat
  (Shop Floor Analyst + mfg-telemetry/mfg-consumption
  connectors; NEVER `--prune`)
- `postgres/` -- seed for the four `mfg_*` databases in the
  host postgres container (`seed.sh`, idempotent). The
  storyline anchor is ECO-2025-118 in `mfg_pdm`: acknowledged
  by Plant 1, PENDING at Plant 2
- `mongodb/` -- plant data store: `docker compose up -d`
  imports ~960 station telemetry docs and ~290 material
  consumption docs (generated deterministically by
  `seed/generate-seed.py`, checked in as ndjson; read-only
  user `sam_ro` for the SAM connectors)
- `eval/` -- dataset `mfg-ops-questions` plus the
  `mfg-ops-quality` gate and the `mfg-ops-model-benchmark`
  (same agent pinned to three models via `spec.models`)
- `observability/` -- the "SAM Manufacturing Ops Demo" Grafana
  dashboard (ConfigMap)
- `cockpit/index.html` -- the Acme plant operations cockpit:
  publishes plant events straight to the sam VPN via
  solclientjs (`ws://localhost:8008`), runs the scripted
  two-movement timeline (one click, deterministic timing) and
  displays agent responses live

## Data storyline (one page)

ECO-2025-118 replaces the HD-20 clutch disc with the sintered
HD-22 (shared by the IX-450 impact driver and the CK-350 clutch
kit) and raises the EOL torque spec from 18.0 to 22.0 Nm.

- `mfg_pdm`: the ECO, the BOMs, and the distribution table --
  Plant 1 ACKNOWLEDGED, Plant 2 PENDING.
- `mfg_plant` (MongoDB): Graz L3 telemetry fails from
  2025-07-28 (measured ~22 Nm vs old spec 17.5-18.5, station
  spec revision B); Hamburg consumption of HD-22 ramps to
  ~460/day vs planned 120/day, balance down to 1850.
- `mfg_scm`: on-hand 1850, safety stock 800, primary supplier
  lead time 10 days, open PO ETA 2025-08-14, qualified
  alternate with 3-day expedite -- the replenishment answer.
- `mfg_oms`: PRD-118-4718 (Graz, IX-450) on QUALITY_HOLD;
  Volta Motors CK-350 program at Hamburg -- the business
  impact, incl. the 45k EUR/h line-down penalty in `mfg_crm`.

## Slides

`slides/SAM v2 - AI Worker Lifecycle Manufacturing.pptx` --
derived from the retail deck, same three-slide structure:

1. AI Worker Lifecycle (unchanged)
2. Live Demo: Event-Driven Manufacturing Operations -- the
   architecture stage: four dynamic DB agents (PDM/OMS/CRM/SCM,
   `mfg_*`), the plant store (MongoDB `mfg_plant`), plants and
   EOL stations streaming over the event mesh
3. The Demo in the Lifecycle -- stage-by-stage checkmarks
   (Shop Floor Analyst built live, mfg-*-schema skills,
   event-driven react + prevent with 8 agents on 4 models)
