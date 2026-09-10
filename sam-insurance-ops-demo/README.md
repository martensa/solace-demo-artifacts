# Event-Driven Claims Operations Demo (SAM v2)

*Ten Thousand Claims, One Process.* 15-minute live demo (plus an
optional 5-minute fraud act), layered as a removable overlay on
top of the base platform in `agent-mesh-deployment/`. Built on
the AI Worker Lifecycle dramaturgy (hire, onboard, teamwork,
improve). The stage: Acme Insurance (motor and property,
Germany-shaped geography), hail cell HZ-0913 over Landkreis
Boeblingen on Saturday evening, 10,400 first notices of loss by
Monday morning -- and THREE event-driven movements from one
click:

1. **Fast Lane** -- 6,200 minor claims (glass, dents, estimate
   under EUR 1,000) are confirmed in seconds by a clerk on the
   fast tier: policy, hail cover HC-7, deductible, drive-in
   slot, three sentences.
2. **React** -- 412 claims stall in the drive-in queue of
   P-BRAENDLE. The incident analysis finds 158 total losses in
   a dent-repair line, the fallback partner switched off since
   January, the RN-3 contract lever and the BaFin day-20 date,
   and proposes ONE action: the cohort clears in 4 days instead
   of 11.
3. **Prevent** -- the forecast for tomorrow's cell HZ-0914 over
   Landkreis Ludwigsburg crosses the warning threshold. The
   team applies the OBSERVED conversion (0.61) instead of the
   playbook's 0.30 to the exposure and stages scanner units and
   a customer warning before the first claim arrives.

Act 2 (optional): a drive-in scanner disagrees with a customer
(60 dents claimed, 14 scanned); the cross-channel fraud and
leakage report holds 58 flagged claims (19 pre-dated photo
sets, 11 duplicate-VIN pairs, 17 over-rate estimates; 52
payment items worth EUR 265,695 to hold before Friday's payment
run -- the EUR at risk) and releases 9,592 of 9,650 motor
claims -- a human decides.

Run of show (rehearsal-verified 2026-09-10, eight live runs):
the Storm Intake Analyst is hired live in the Builder BEFORE the
click (1:00-4:00 show time; never click before it shows
Deployed), the click at 4:00 is T+0. Measured on the
Orchestrator path: Fast Lane first confirmation T+0:15 and all
eight by T+0:38; stalled event T+0:25 -> Stalled Cohort Report
~T+3:36; forecast event T+5:00 -> Storm Readiness Recommendation
~T+6:50; with the fraud checkbox the scanner-mismatch event
fires at T+8:00 (after the readiness report, so it never
competes with React/Prevent for the one analyst) and the fraud
report lands about 2 minutes after the event (~T+10), waiting in
its panel for the optional Act 2.

Start with [talk-track.md](talk-track.md) -- the demo script
(v0.2, rehearsal-verified: beats, click paths, the Builder
green-path prompt synced with the fallback analyst yaml, failure
signatures with stage responses; every READ-ALOUD quote is
verbatim report wording from the rehearsal runs).

## Install / remove

With the base platform running (one-click deployment plus
`sam auth login`, see `agent-mesh-deployment/README.md`):

```bash
./install.sh
```

Idempotent: starts the host data stores (postgres/pgadmin with
the seeded `acme_insurance` database, MongoDB
`acme-claims-mongo` on port 27017 incl. first-run generated
seed, and the knowledge base -- Qdrant `acme-knowledge-qdrant`
plus the `acme-knowledge-mcp` MCP server on port 8765 with its
one-shot seed container), applies the insurance core package
(`core/`), the five model aliases, the demo mesh overlay, the
eval package and the demo dashboard. By default it leaves the
Storm Intake Analyst REMOVED while the three MongoDB connectors
stay pre-provisioned: the live Builder beat creates only the
agent binding them (one config, no connector sub-tasks -- fast
and reliable on stage).

Only ONE demo overlay runs at a time: `install.sh` refuses to
install while another demo's entrypoint (`shop-events`,
`plant-events`) is on the platform (pointing at its
`uninstall.sh`), and stops any other demo's mongo container
(`retail-pos-mongo`, `mfg-plant-mongo`) occupying port 27017.

```bash
./uninstall.sh
```

### Script flags

`install.sh`:

- (no flag) -- clean state for the live demo: Storm Intake
  Analyst absent, connectors pre-provisioned
- `--with-analyst` -- keep the Storm Intake Analyst agent
  (rehearsals; skips the live Builder beat)

`uninstall.sh`:

- (no flag) -- removes the demo overlay (entrypoint, workflows,
  agents, the three intake connectors) AND the insurance core
  (agents, connectors, skills), the eval experiments and
  dataset (INCLUDING their run history), the demo dashboard,
  the `acme-claims-mongo` container INCLUDING its data volume,
  and the knowledge-base stack INCLUDING the Qdrant data volume
  and the embedding-model cache (the next `install.sh`
  re-downloads the model once, ~2 min)
- `--keep-core` -- remove only the overlay; keep the core for
  fast re-install
- `--dry-run` -- preview everything without changing anything
- `--purge-data` -- additionally DROP the `acme_insurance`
  postgres database; combined with the default mongo and
  knowledge-base removal this deletes the demo COMPLETELY, data
  and volumes included (a fresh `install.sh` re-seeds
  everything in a minute or two)

Always kept: the SAM infrastructure (models, RBAC,
developer-mcp, observability) and the shared postgres/pgadmin
host containers.

## Contents

- `talk-track.md` -- the demo script (English)
- `install.sh` / `uninstall.sh` -- demo lifecycle on top of the
  base platform (idempotent)
- `preflight.sh` -- automated Appendix A checklist with
  auto-fix; ends READY / NOT READY (run ~15 min before going
  live): login, cluster, models, platform resources (incl. the
  MCP connector and the forbidden analyst), postgres spot-check
  (412 cohort / 640 Braendle / 8,900 exposure), mongo counts,
  knowledge base (collection points + MCP `/health`), broker
  WS, dashboard, evals
- `demo-links.sh` -- prints direct SAM UI links for the demo
  windows (workflows are name-based and stable; agent,
  connector and entrypoint links are resolved by ID via the
  platform API)
- `core/` -- the insurance CORE package (`sam config apply`):
  the `Acme Insurance DB` postgres connector, the `Acme Claims
  Knowledge` MCP connector, the `acme-insurance-schema` and
  `acme-knowledge-guide` skill bundles, the Acme Insurance
  Query Expert and the Acme Claims Knowledge Expert. Removed by
  uninstall.sh unless `--keep-core`
- `mesh/` -- declarative demo resources (`sam config apply`):
  Fast Lane Clerk (fast tier), Claims Incident Reporter +
  Storm Readiness Planner + Fraud Case Reporter (workflow
  tier; they merge in the WORKFLOW variant only), the
  `stalled-cohort-report`, `storm-readiness` and
  `cross-channel-fraud-report` workflows (in
  `stalled-cohort-report` the intake node runs after the
  Insurance DB node on purpose: `fnol_intake` carries no status
  or partner, so the cohort is selected by the claim_id range
  the Insurance DB returned), the `claims-events`
  event-mesh entrypoint (four rules: minor FNOL -> clerk,
  stalled cohort -> incident report, forecast threshold ->
  readiness recommendation, scanner mismatch -> fraud report).
  On the event path the Orchestrator fans out to the
  specialists and then MERGES and writes the report itself,
  with the report skeleton inline in the rule -- rehearsal
  runs 4-5 showed the reporter hop to be the one flaky link
  (peer-wait timeouts after ~30 s of silence, reports handed
  back as artifact references the mesh result cannot resolve)
- `fallback/` -- break-glass configs for the live Builder beat
  (Storm Intake Analyst + the `fnol-intake`, `weather-cells`,
  `scanner-results` connectors; NEVER `--prune`)
- `postgres/` -- seed for the `acme_insurance` database in the
  host postgres container (`seed.sh`, idempotent; the bulk rows
  are generated inside Postgres deterministically, the story
  anchors are explicit statements)
- `mongodb/` -- claims intake store `acme_claims`:
  `docker compose up -d` generates the 10,400 intake documents
  (plus 63 repeat contacts), 3 weather cells and ~1,040 scanner
  results deterministically in the init scripts (seeded PRNG,
  no checked-in data files; read-only user `sam_ro` for the
  SAM connectors)
- `qdrant/` -- the knowledge base: Qdrant plus a small MCP
  server (streamable-http on port 8765, path `/mcp`, `/health`
  for preflight) exposing `search_policy_wordings`,
  `search_claims_guidelines`, `search_partner_contracts`,
  `search_storm_playbooks` and `get_knowledge_document`; the
  corpus lives in `seed/documents.yaml` and is embedded into
  the `acme_knowledge` collection by the one-shot seed
  container
- `eval/` -- dataset `ins-ops-questions` plus the
  `ins-ops-quality` gate and the `ins-ops-model-benchmark`
  (same agent pinned to three models via `spec.models`)
- `observability/` -- the "SAM Insurance Ops Demo" Grafana
  dashboard (ConfigMap `dashboard-sam-insurance-ops`)
- `results/acme-claims-results.html` -- self-contained,
  theme-aware results page rendering the three reports (KPIs,
  findings, options, the ONE action, the human decision as an
  event) with the rehearsal-verified numbers; the leave-behind
  / recap view of what the audience watched happen
- `cockpit/index.html` -- the Acme Insurance claims cockpit:
  publishes the cell observation, the FNOL burst and the three
  business events straight to the sam VPN via solclientjs
  (`ws://localhost:8008`), runs the scripted timeline (one
  click, deterministic timing: stalled event T+0:25, forecast
  T+5:00, scanner mismatch T+8:00 with the "Include fraud act"
  checkbox -- CFG `stalledAtS` / `forecastAtS` / `scannerAtS`),
  displays the Fast Lane confirmations and the three reports
  live, and publishes the human decisions
  (`acmeins/claims/decision/...`) from the Approve buttons;
  break-glass buttons re-fire any business event. Keep it in
  its own visible window: hidden browser tabs throttle its
  timers

## Data storyline (one page)

"Today" in the fiction is Monday 2026-07-20, 10:00. Hail cell
HZ-0913 (3.5 cm, warning level 3) crossed Landkreis Boeblingen
on Saturday 2026-07-18 at 18:40. The story lives in THREE
stores, and every report correlates all three:

- `acme_insurance` (Postgres, six `ins_*` tables): 10,400
  claims for HZ-0913 (9,650 motor, 750 property; MINOR 6,200,
  MODERATE 3,600, SEVERE 600). The stalled cohort
  CLM-0913-06001 to 06412 sits in AWAITING_WORKSHOP_SLOT at
  P-BRAENDLE since Sunday morning; 293 of their policies carry
  the repair-network clause RN-3. P-BRAENDLE carries 640
  assignments against 120 scans a day; P-DELLENDOC is INACTIVE
  since 2026-01-01 over the unsigned parts-channel clause PC-4.
  Exposure: 31,600 motor policies in BOEBLINGEN (15,800 without
  garage), 17,400 in LUDWIGSBURG (8,900 without garage, plus
  2,300 property). Fraud anchors: 17 estimates of W-0471 at
  +38% over the contracted rates (9 with an identical line
  item), 11 duplicate claim pairs (22 claims), payment run
  PR-2026-30 (3,900 items, EUR 14,200,000, Friday 2026-07-24
  16:00) with items already scheduled for 18 of the 19
  pre-dated claims, all 11 APP legs, 6 of the 11 VOICE_AGENT
  legs and the 17 W-0471 estimates.
- `acme_claims` (MongoDB, three collections): `fnol_intake` --
  one document per intake message with narrative, photos (EXIF
  timestamps), damage signals and channel; 158 of the stalled
  cohort carry the total-loss signature (glass shattered, roof
  deformed, more than 150 dents), 63 customers called twice, 4
  filed a complaint; 19 claims have photos taken 6-9 days
  before the cell; 11 vehicles were reported via APP and
  VOICE_AGENT within 48 h. `weather_cells` -- HZ-0913
  (observed, exposure 15,800 no-garage vehicles), HZ-0914
  (forecast, Tue 2026-07-21 16:00-19:00, Ludwigsburg, 8,900
  no-garage vehicles, 2,300 property) and HZ-0907 (the 2 cm
  cell the playbook was calibrated on, conversion 0.28).
  `scanner_results` -- one document per drive-in scan;
  CLM-0913-08103 claimed 60 dents, the scanner counted 14.
- `acme_knowledge` (Qdrant behind the MCP server): policy
  wordings (HC-7 hail cover, RN-3 steering clause with the
  5-working-day rule, TL-1 total-loss definition), claims
  guidelines (Fast Lane criteria, Total Loss Fastlane, the
  BaFin 30-day rule with day-20 escalation, the fraud indicator
  guideline with the GDV principle), partner contracts
  (Braendle second-shift option, Dellendoc's blocked renewal
  and the interim contract IC-2, RoadAssist, RentaFleet, the
  contracted rates with the 25% review threshold) and storm
  playbooks (NatCat v4 with the 0.30 planning conversion and
  the capacity options, lessons learned from HZ-0907 and the
  Reutlingen 2023 cell).

The arithmetic the reports must reproduce (numbers as the
rehearsed reports of 2026-09-10 stated them): observed
conversion 9,650 / 15,800 = 61.08% (one claim per 1.6 exposed
vehicles) versus the playbook's 30%; expected HZ-0914 volume
5,436 motor FNOLs in 48 h versus 2,670 planned (plus 414
property); capacity gap in Ludwigsburg 30.2 scan-days versus
14.8 at 180 scans a day, and about 121 rental cars versus 35 on
hand; the cohort clears in 4 days instead of 11 with the ONE
action (158 to the Fastlane, Dellendoc under IC-2 at 90 a day,
Braendle's second shift to 180 a day: 1,260 / 120 = 10.5 -> 11
days before, (1,260 - 158) / 270 = 4.08 -> 4 days after); 58
flagged claims in 47 cases held (19 pattern A + 11 VIN pairs =
22 claims in pattern B + 17 pattern C), 52 payment items of
the four flagged ranges in PR-2026-30 to hold (R1 18 items EUR
87,047.19 for 08101..08119, R2 11 items EUR 47,695.26 for
08201..08211, R3 6 items EUR 25,523.57 for 08301..08306, R4 17
items EUR 105,429.24 for 08401..08417) = EUR 265,695.26, which
is also the EUR at risk (basis: the payment items of the
flagged ranges), 9,592 of 9,650 released.

## Slides

`slides/SAM v2 - AI Worker Lifecycle Insurance.pptx` -- adapted
from the manufacturing deck (same skeleton, claims vocabulary),
four slides:

1. AI Worker Lifecycle (unchanged)
2. The Use Case: One Hail Cell, Two Movements -- the story
   slide: stage (Acme Insurance, the cell, the five channels,
   the three stores) plus one card per movement (React with the
   cohort numbers at ~T+4, Prevent with the conversion math at
   ~T+8), the causal-chain strip (one click -> one event ->
   react + prevent -> the human approves, as an event) and the
   Act 2 strip (fraud & leakage, the human decides); doubles as
   the CLOSE image
3. Live Demo: Event-Driven Claims Operations -- the
   architecture stage: Query Expert (Postgres `acme_insurance`),
   Knowledge Expert (Qdrant via MCP), Fast Lane Clerk (fast
   tier), the three reporters/workflows, the intake stream
   (MongoDB `acme_claims`, Storm Intake Analyst built live), the
   five FNOL channels and the weather feed as event sources on
   the mesh, story beats 1-2-3
4. The Demo in the Lifecycle -- stage-by-stage checkmarks
   (Storm Intake Analyst built live, acme-* skills, three
   connector technologies, event-driven react + prevent + fraud
   with 8 agents on 3 model tiers (4 model families incl. the
   benchmark), human approval as an event, eval gate +
   benchmark, Grafana cost per claim)
