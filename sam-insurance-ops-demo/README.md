# Acme Insurance Demos (SAM v2) -- Claim Triage and Claims Operations

Two live demos on one data set, layered as removable overlays on
top of the base platform in `agent-mesh-deployment/` (SAM v2
2.225.14, namespace `sam-solace-lab`). The stage is Acme
Insurance (motor and property, Germany-shaped geography), hail
cell HZ-0913 over Landkreis Boeblingen on Saturday 2026-07-18 at
18:40, and a frozen Monday morning (2026-07-20 10:00 UTC) with
10,400 first notices of loss in three stores.

- **Default profile -- "Claim Triage in 30 Seconds"** (10 min,
  governance-first): Solace Agent Mesh as the control layer over
  the agents a customer already has. One claim comes in as an
  event, a four-node schema-bound workflow triages it in about 27
  to 33 s through four platform agents and ONE external agent that
  runs outside the platform, a decision card lands in a cockpit, a
  named human approves -- and every claim of the talk (identity,
  audit, latency, tokens, quality over time) is proven in
  Activities, Grafana, Tempo and the Evaluations lab. Script:
  [talk-track.md](talk-track.md).
- **Extended profile -- "Event-Driven Claims Operations"**
  (15 min + optional 5-min Act 2): the AI Worker Lifecycle
  dramaturgy (hire in the Builder, click, react, prevent,
  improve, fraud act). Script:
  [talk-track-extended.md](talk-track-extended.md), installed
  with `./install.sh --extended`.

The two profiles are mutually exclusive on the platform: both
subscribe to `acmeins/claims/fnol/received/...`, so `install.sh`
removes the other profile's entrypoint (`claims-events` versus
`claims-triage`) and says why.

## The scenario (default profile)

The cockpit publishes ONE persistent FNOL event for the selected
claim on `acmeins/claims/fnol/received/<severity>/<claim_id>`.
The `claims-triage` entrypoint (rule `fnol_received`, identity
`power_user@solace.lab`) passes the payload through
(`inputExpression: "input.payload"`) and starts the `claim-triage`
workflow. Three nodes run in parallel: `policy` (Acme Insurance
Query Expert, two fixed SQL queries on `acme_insurance`, 22-field
contract), `intake` (Claims Intake Liaison, whose
`interAgentCommunication` allow list names exactly ONE peer: it
delegates one task to the EXTERNAL Claims Intake Analyst reading
MongoDB and hands its values back unchanged, 12-field contract)
and `rules` (Acme Claims Knowledge Expert, three focused searches
with top_k 3 against Qdrant behind an MCP server, 5-field
contract). The `decision` node (Claims Triage Decision, fast tier,
no tools) `depends_on` all three and merges them against the
decision matrix into the 14-field decision contract: APPROVE /
HOLD / REFER plus a lane. In the workflow's `output_mapping` every
optional field goes through `coalesce` with a fallback, so one
dropped key cannot fail the run; `claim_id`, `decision` and `lane`
stay bare on purpose (a loud failure beats a blank card). The
result lands on `acmeins/claims/result/triage` (errors on
`.../result/error`), the cockpit renders the card with "decided in
n s", and the Approve button publishes
`acmeins/claims/decision/<claim_id>` with `approved_by:
claims.lead@acme-insurance`.

Measured on the live platform (2026-09-16), from publishing the
FNOL event to the decision on the result topic: CLM-0913-00001
APPROVE / FAST_LANE 27.7 s, CLM-0913-00002 APPROVE / FAST_LANE
26.8 s, CLM-0913-08103 HOLD / SPECIAL_INVESTIGATIONS 30.6 s,
CLM-0913-08891 APPROVE / STANDARD 32.7 s -- about 27 to 33 s.
Typical nodes in one run: policy 13 s, intake 19 s (of which the
external analyst itself is 5 s), rules 9 s, decision 12 s. The
fan-out is parallel, so the critical path is intake plus decision.

## Install / remove / preflight

With the base platform running (one-click deployment plus
`sam auth login solace-lab --url https://sam.solace.lab`, see
`agent-mesh-deployment/README.md`):

### Default profile (triage / governance)

```bash
./install.sh          # triage profile (default)
./preflight.sh        # profile-aware checklist + dry fire
./demo-links.sh       # direct UI links for the window setup
./uninstall.sh        # removes both overlays + the external agent
```

`install.sh` is idempotent. Common steps: the host data stores
(postgres/pgadmin with the seeded `acme_insurance` database,
MongoDB `acme-claims-mongo` on port 27017, Qdrant plus the
`acme-knowledge-mcp` server on port 8765 with their first-run
seeds), the insurance core package (`core/`) and the five model
aliases. Triage steps: the external agent (`kubectl apply -f
external-agent/`, rollout wait, poll for the discovered card
"ClaimsIntakeAnalyst"); the triage overlay (`sam config apply`
in `triage/`: the liaison and decision agents and the workflow);
the entrypoint rendered from
`triage/entrypoints/claims-triage.yaml.template` AFTER the
workflow exists (`__WORKFLOW_RUNTIME__` ->
`workflow_<id>`, see "Known limits") plus a wait for the
gateway's "persistent receiver started"; the eval package plus
the watchlist; the Grafana platform-DB grant and datasource; both
dashboard ConfigMaps. It prints which cockpit page to open.

`preflight.sh` detects the profile from the entrypoint on the
platform. Triage checks: external agent pod Running and card
discovered, workflow deployed and running, entrypoint receivers,
decision agent present, dashboards and datasource, `grafana_ro`
SELECT on the platform DB, Tempo traces in the last 24 h (warn
only), completed pre-runs for the five experiments, and a DRY
FIRE (`node tools/fire-claim.js --claim CLM-0913-00002 --wait 90`)
that must print a decision. `--skip-evals` skips the pre-run.

### Extended profile (lifecycle demo)

```bash
./install.sh --extended                 # clean state: analyst absent
./install.sh --extended --with-analyst  # rehearsals: keep the analyst
./preflight.sh
./uninstall.sh
```

The extended flow is documented in `talk-track-extended.md`;
window C is `cockpit/extended.html`.

### Script flags

`install.sh`: (no flag) triage profile; `--extended` the
lifecycle profile (`mesh/`, the `claims-events` entrypoint, the
Storm Intake Analyst left ABSENT for the live Builder beat);
`--with-analyst` (with `--extended`) keeps the Storm Intake
Analyst for rehearsals.

`uninstall.sh`: (no flag) removes BOTH overlays (the
`claims-triage` entrypoint, `claim-triage` workflow, triage
agents and the external agent via `kubectl delete -f
external-agent/`; the extended profile's entrypoint, workflows,
agents and intake connectors), the eval experiments and datasets
INCLUDING run history, both dashboards, the insurance core, the
`acme-claims-mongo` container INCLUDING its data volume, and the
knowledge-base stack INCLUDING the Qdrant volume and the
embedding-model cache (the next `install.sh` re-downloads the
model once, ~2 min); `--keep-core` removes only the overlays
(fast re-install or profile switch); `--dry-run` previews;
`--purge-data` additionally DROPS `acme_insurance`. Always kept:
the SAM infrastructure (models, RBAC, developer-mcp,
observability) and the shared postgres/pgadmin containers. NEVER
`sam config apply --prune`.

## Contents

- `talk-track.md` -- the 10-minute governance script (default
  profile); `talk-track-extended.md` -- the 15-minute lifecycle
  script (extended profile, formerly `talk-track.md`)
- `install.sh` / `uninstall.sh` / `preflight.sh` -- profile-aware
  demo lifecycle and the automated Appendix A checklist with
  auto-fix and dry fire (READY / NOT READY)
- `demo-links.sh` -- direct SAM UI links for both profiles
  (pages, the workflow "Claim Triage", agents incl. the external
  analyst, entrypoint, Grafana uid `sam-claims-governance`, the
  Tempo explore link; IDs are resolved per install)
- `core/` -- the insurance CORE package (`sam config apply`):
  the `Acme Insurance DB` postgres and `Acme Claims Knowledge`
  MCP connectors, the `acme-insurance-schema` and
  `acme-knowledge-guide` skills, the two experts (both carry
  `modelProvider: ["${INS_EXPERT_TIER}"]`, the manifest variable
  that `install.sh` sets per profile: default `fast` (Haiku 4.5)
  for triage, `general` for `--extended`; every agent of the
  triage profile runs on `fast`); kept by `--keep-core`
- `triage/` -- the default overlay (all CLI-applied):
  `manifest.yaml`, `agents/Claims Intake Liaison.yaml` (fast tier,
  `toolsets: []`, and an `interAgentCommunication` allow list with
  exactly one entry, `ClaimsIntakeAnalyst` -- its whole reach into
  the estate outside the platform, declared),
  `agents/Claims Triage Decision.yaml` (fast tier, no tools, the
  decision matrix), `workflows/claim-triage.yaml` (four nodes with
  22/12/5/14-field contracts, schema-bound, `fail_fast: false`,
  `output_mapping` with `coalesce` fallbacks; the `intake` node
  targets the liaison, which makes the one hop to the external
  analyst), `entrypoints/claims-triage.yaml.template` plus
  `manifest.yaml.template` (both rendered into the git-ignored
  `.rendered/` by `install.sh`)
- `external-agent/` -- Kubernetes manifests for the agent that
  runs OUTSIDE the platform (namespace `sam-solace-lab-agents`):
  `sam-claims-intake-agent-config.yaml` (ConfigMap, SAM v1 SDK
  app YAML), `sam-claims-intake-agent-deployment.yaml`,
  `sam-claims-intake-agent-secret.yaml` (demo values, committed),
  `README.md` (what is external and why)
- `mesh/`, `fallback/` -- the extended overlay (Fast Lane Clerk,
  the three reporter/planner agents, the `stalled-cohort-report`,
  `storm-readiness` and `cross-channel-fraud-report` workflows,
  the `claims-events` entrypoint) and its break-glass configs
- `cockpit/index.html` -- the single-card triage cockpit
  (default profile): claim picker (CLM-0913-00001 clean,
  CLM-0913-08103 suspicious), ONE button "Claim comes in",
  stepper, decision card, Approve, event stream, break-glass
  "Re-fire same claim" / "Reset"; solclientjs via
  `ws://localhost:8008`
- `cockpit/extended.html` -- the extended profile's cockpit
  (formerly `index.html`); `cockpit/solclient.js` -- the Solace
  JavaScript API used by both cockpits and by `tools/fire-claim.js`
- `tools/fire-claim.js` -- node CLI: publishes the cockpit's FNOL
  payload for a claim (`--claim`, default CLM-0913-00002; knows
  00001, 00002, 08103, 08891), waits `--wait` seconds for the
  decision, prints the decision JSON and elapsed seconds; exit 0
  on a decision, 1 on timeout. Used by preflight and rehearsals
- `eval/` -- datasets `ins-ops-questions`, `ins-claims-rules`,
  `ins-triage-decisions`, `ins-guardrails` and the experiments
  under "Evaluation experiments"
- `observability/` -- `dashboard-sam-claims-governance.yaml`
  ("SAM Claims Governance", default profile, uid
  `sam-claims-governance`) and `dashboard-sam-insurance-ops.yaml`
  ("SAM Insurance Ops Demo", extended profile)
- `postgres/`, `mongodb/`, `qdrant/` -- the three stores: the
  `acme_insurance` seed (`seed.sh`, idempotent), the intake store
  `acme_claims` (`fnol_intake`, `weather_cells`,
  `scanner_results`; generated at first start, read-only user
  `sam_ro`; `seed/02-anchors.js` also creates the view
  `claim_intake_facts`, which joins the scan, the other claims on
  the same VIN, the repeat contacts and the claim's hail cell and
  computes `photos_before_cell` and `days_before_cell` against
  that cell's start -- the analyst's query collapses to one
  `$match`, which took a 900-token pipeline and about 6 s per run
  off the critical path), the knowledge base (Qdrant plus the MCP
  server with `search_policy_wordings`, `search_claims_guidelines`,
  `search_partner_contracts`, `search_storm_playbooks`,
  `get_knowledge_document`; corpus in `seed/documents.yaml`)
- `results/`, `slides/` -- the extended profile's results page
  and deck (see "Slides")

Companion files in `agent-mesh-deployment/` (shared
infrastructure, applied by `install.sh`):
`manifests/observability/grafana-datasource-sam-platform-config.yaml`
(Grafana datasource `sam-platform-config-db` on the platform DB)
and `scripts/observability/grant-grafana-platform-db.sh`
(idempotent SELECT grant for `grafana_ro`).

## Data anchors (default profile)

Frozen snapshot "now" = Monday 2026-07-20 10:00 UTC; hail cell
HZ-0913 started 2026-07-18T18:40:00Z over district BOEBLINGEN.

- **CLM-0913-00001 -- the clean claim.** Lena Hartmann
  (CUS-007919, private, no complaint), VW Golf, policy POL-104211
  ACTIVE MOTOR_COMPREHENSIVE with hail cover and the repair
  network clause RN-3, deductible EUR 300, Sindelfingen. MINOR,
  reported through the APP, estimate EUR 640, reserve EUR 750,
  drivable; intake FNOL-0913-00001: 16 dents, no glass, roof ok,
  three photos taken 2026-07-18 18:47-18:53 UTC (AFTER the cell
  start), no repeat contact, no duplicate VIN, no scanner
  document. Expected: **APPROVE / FAST_LANE**, network route to
  the ACTIVE drive-in partner of the district, P-BRAENDLE
  "Braendle Drive-In Hail Center", Sindelfingen (120 scans a day,
  640 claims already awaiting a slot; P-DELLENDOC is INACTIVE
  since 2026-01-01); deductible EUR 300 once per event (PW-HC-7,
  PW-RN-3, CG-FL-1).
- **CLM-0913-08103 -- the suspicious claim.** Ben Meier
  (CUS-003858), Skoda Octavia, policy POL-003858 ACTIVE
  MOTOR_PARTIAL with hail cover, deductible EUR 150, no network
  clause, Sindelfingen. MODERATE, channel DRIVE_IN_SCANNER,
  AWAITING_WORKSHOP_SLOT at P-BRAENDLE, estimate EUR 6,800,
  reserve EUR 7,800; intake: 60 dents claimed, three photos taken
  2026-07-11 (7.3 days BEFORE the cell), scanner SCAN-0913-08103:
  14 dents scanned, scanner estimate EUR 1,190, mismatch flag.
  Expected: **HOLD / SPECIAL_INVESTIGATIONS** with the two
  indicators; per CG-FR-5 a human specialist decides.
- **CLM-0913-00002** -- the pre-flight dry-fire claim (warms the
  agents; never shown in the cockpit). **CLM-0913-08891**
  (optional, Ford Focus, Herrenberg, 28 dents, windscreen
  shattered) -> APPROVE / STANDARD.

## What runs outside the platform, and why

The **Claims Intake Analyst** (`external-agent/`) is a SAM v1
Python-SDK agent in its own Deployment in namespace
`sam-solace-lab-agents`, on its own model (Haiku, set in its own
Secret), with its own read-only MongoDB access to the intake
store. It publishes its agent card over the broker and speaks A2A
only (leaf agent, discovers nobody). Agent Management shows it as
a *discovered* agent: no Undeploy button, Created By "--", "Chat
with Agent" works. It stands in for the agent the customer
already runs in Databricks or Azure: nothing is migrated, and the
mesh still governs every hop -- the card, the identity on each
request, the latency in Activities and Tempo. What the platform
does NOT see: its tokens, model calls and inner tool calls. It
answers a per-claim request with ONE tool call against the
`claim_intake_facts` view (`auto_detect_schema` off, no artifact
tool group -- both are prompt weight on every request); the raw
collections stay reachable through `fnol_intake_query`,
`scanner_results_query` and `weather_cells_query`.

The `intake` node reaches it through the **Claims Intake
Liaison**, a platform agent with `toolsets: []` whose
`additionalConfigurations` carry
`interAgentCommunication.allowList: [ClaimsIntakeAnalyst]`. That
key IS the mechanism: an agent without it has no delegation tool
at all (it only reaches its own `sub_task`), and the built-in
Orchestrator carries the same key set to `["*"]`. So the liaison
may call exactly one agent in the world, by name, declared in its
config and reviewable in the UI -- reach across the platform
boundary is declared and enforced, not implicit. It delegates one
task per claim and hands the analyst's values back unchanged; the
contract the answer must satisfy is the node's output schema on
the platform. Routing the same hop through the Orchestrator works
too, but costs about 13 s of Opus-tier overhead on the critical
path, and an external v1 agent cannot be a workflow node directly
(see "Known limits"). A Databricks or Azure host would differ only
in the `MONGO_*` and model variables of the Secret;
`external-agent/README.md` has the details.

## The governance dashboard

"SAM Claims Governance" (ConfigMap
`dashboard-sam-claims-governance`, folder SAM, refresh 10 s,
datasources prometheus / loki / tempo / `sam-platform-db` /
`sam-platform-config-db`). Six rows:

1. **Control layer -- is the estate under control?** --
   components up, broker links, registered agents (platform
   agents only; the discovered analyst is not counted), claims
   in flight, the agent roster and workflows/entrypoints tables.
2. **The claim -- from event to decision** -- claims events per
   minute, decision latency p50/p95, agent step duration p95 per
   agent, the Tempo panel "Every hop of a claim is a span".
3. **Who did what -- audit and security** -- tool executions by
   user and tool, agent calls per agent, external agent traffic
   (the analyst's pod logs), auth failures plus
   capability-widening blocks, RBAC roles -> scopes and IdP group
   -> role tables.
4. **Model management -- which model works for whom, at what
   cost** -- tokens per agent and model, LLM latency p95 per
   model, the alias table, an ILLUSTRATIVE cost stat, tokens per
   user.
5. **Quality -- evaluations over time** -- score per experiment /
   model / evaluator, latest runs, watchlist agents, judge tokens.
6. **The proof** -- Activities, Tempo and Loki pointers, and the
   note that RBAC grants log at DEBUG only (no "denied" panels;
   the negative signals are auth failures and widening blocks).

## Evaluation experiments

All experiments target AGENTS (workflows cannot be targets);
evaluators are platform-seeded (LLM Judge, Factuality, Closed QA,
Security, Response Match); pass = score >= 0.5; one LLM-judge
call ~40 s. The watchlist holds Acme Insurance Query Expert, Acme
Claims Knowledge Expert and Claims Triage Decision.

| Experiment | Dataset | Target agent | Evaluators (primary first) | Stage use |
| --- | --- | --- | --- | --- |
| `ins-triage-decision` | `ins-triage-decisions` (3 rows: clean, suspicious, synthetic total loss -- the exact fan-in text of the decision node) | Claims Triage Decision | LLM Judge, Response Match | LIVE run started at 4:30, ~75 s, read in beat 5 |
| `ins-claims-rules` | `ins-claims-rules` (5 rulebook questions verified against `qdrant/seed/documents.yaml`) | Acme Claims Knowledge Expert | Factuality, Closed QA | pre-run |
| `ins-guardrails` | `ins-guardrails` (prompt injection, destructive SQL, role escalation) | Acme Insurance Query Expert | Security, LLM Judge | pre-run |
| `ins-ops-quality` | `ins-ops-questions` | Acme Insurance Query Expert | LLM Judge, Factuality | pre-run (production gate) |
| `ins-ops-model-benchmark` | `ins-ops-questions` | Acme Insurance Query Expert pinned to `workflow`, `reasoning`, `fast` | LLM Judge, Factuality | pre-run (three models, one dataset) |

Run by hand:
`sam eval run ins-triage-decision --url https://sam.solace.lab --threshold 0.8`

## The extended profile

`./install.sh --extended` installs the lifecycle demo: the Storm
Intake Analyst is hired live in the Builder before the click, the
cockpit (`cockpit/extended.html`) runs the scripted storm
timeline and the three reports land as event-driven runs. Run of
show, measured landing times, the Builder prompt, its own known
limits and the storyline of the full 10,400-claim set live in
`talk-track-extended.md` and `results/acme-claims-results.html`.

## Known limits (short)

Full list with stage responses: `talk-track.md`, Appendix C.

- Two platform bugs on the event -> workflow path (empty
  `promptTemplate` for workflow targets, DATAGO-148462; the
  request topic uses the workflow NAME while the runtime listens
  on `workflow_<id>`) -- worked around by rendering the entrypoint
  with the runtime name after the workflow exists. The name
  changes per install: re-run `install.sh`, never edit
  `triage/.rendered/`.
- Node input templates render only whole-string `{{...}}`
  values; external v1 agents cannot be workflow nodes, and a
  platform agent has no peer-delegation tool in 2.225.14 unless
  its config declares one (otherwise it only reaches its own
  `sub_task`) -- the Claims Intake Liaison declares exactly one
  peer and makes the hop on the fast tier.
- Never tell a schema-bound node agent HOW to format its answer:
  the platform injects its own structured-invocation instruction
  and the agent fulfils it through a save_artifact block. Asking
  for "only the JSON object" leaves the artifact empty and the
  node output null. For the same reason the liaison is told to
  call NO tool but its peer tool, and all agents write ASCII
  ("EUR 300", plain hyphens): non-ASCII arrives mangled at the
  cockpit.
- The platform does not see the external agent's tokens or tool
  calls; it is not in `sam_component_count`.
- No RBAC "denied" log lines (grants log at DEBUG); retention
  Tempo 48 h, Loki 7 d, Prometheus 7 d.
- Evaluations target agents, not workflows; the decision is an
  LLM output validated against a schema -- a `null` section
  degrades to REFER.

## Slides

`slides/SAM v2 - Claim Triage (governance demo).pptx` is the deck
of the default profile, adapted from the lifecycle deck. Slide 3
is the one to open first: it shows the whole setup at a glance --
the event mesh, the one entrypoint, the one workflow, which agent
reads which store, and the dashed boundary around the one agent
that runs outside the platform, with the allow list that lets it
be reached. Slide 2 describes the single scenario and both
claims; slide 4 is the optional lifecycle recap.

`slides/SAM v2 - AI Worker Lifecycle Insurance.pptx` is the
original deck of the EXTENDED profile and is left untouched.
