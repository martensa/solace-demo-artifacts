# Event-Driven Manufacturing Operations — Live Demo Script

> **Status: v1.0 — rehearsal-hardened.** Structure, beats,
> click paths, the Builder green-path prompt and the section-7
> timings/READ-ALOUD quotes are verified against the full dress
> rehearsal of 2026-08-11 (one click, 13/13 tasks completed,
> real report texts).

**Title slide:** Event-Driven Manufacturing Operations —
*The Line Never Stops.*

The red thread is the AI Worker Lifecycle (HIRE -> ONBOARD ->
TEAMWORK -> IMPROVE). The signature of this demo: TEAMWORK has
**two movements** from **one click** —

1. **React** — an end-of-line failure at Plant 2 (Graz) triggers
   the quality incident analysis. Root cause: ECO-2025-118
   (HD-22 clutch disc + new torque spec) was never acknowledged
   in Graz. The part arrived, the data didn't.
2. **Prevent** — the same ECO ramped HD-22 consumption at
   Plant 1 (Hamburg) past the old planning parameters. The
   coverage gauge crosses the red line, the threshold event
   fires, and a replenishment recommendation lands before the
   line stops.

## Personas and RBAC — who is logged in when

| Persona | Where | Role in the demo |
| --- | --- | --- |
| `sam_admin` | Browser window A | Bootstrap admin, the "hiring manager": roster (3), Builder (4), tour (5), deploy + first task (6), evals (8) |
| `power_user@solace.lab` | Browser window B | Operations persona: Activities (7). All event-triggered runs are attributed to it via the entrypoint's `defaultUserIdentity` — they appear in ITS Activities and under its name in the chargeback panel |

The RBAC story tells itself: the admin hires and configures,
the operations persona owns the event-driven work, and every
token lands on the right name in chapter 8.

## Timing at a glance (20:00 total)

| # | Beat | Time |
| --- | --- | --- |
| 1 | Lifecycle — slide 1 | 0:00–1:00 |
| 2 | Scenario — slides 2+3 (use case, architecture) | 1:00–2:30 |
| 3 | HIRING — roster and the gap | 2:30–3:30 |
| 4 | ONBOARDING kickoff — Build with AI | 3:30–4:30 |
| 5 | Workplace tour (while the Builder runs) | 4:30–7:30 |
| 6 | ONBOARDING complete — deploy + first task | 7:30–9:30 |
| 7 | TEAMWORK — the cockpit, two movements | 9:30–16:30 |
| 8 | IMPROVEMENT — measure the workforce | 16:30–18:45 |
| 9 | WRAP — the lifecycle, closed | 18:45–20:00 |

## 2. Scenario — slides 2+3 (1:00–2:30)

**DO**: Start on slide 2 ("The Use Case: One Engineering
Change, Two Movements") for the story — company, plants, the
ECO trigger and the two movement cards. Switch to slide 3 (the
architecture stage) at "the interesting part". Slide 2 returns
in the WRAP: its bottom strip IS the causal-chain closer (one
click -> one event -> react + prevent -> no human in the loop).

**SAY** (core of it):

> "Acme Manufacturing. Two divisions on one platform: power
> tools — impact drivers, angle grinders — and automotive
> components — brake calipers, clutch kits, bearings — supplied
> to OEMs. Two plants: Hamburg builds automotive, Graz builds
> power tools. The classic IT landscape: accounts in a CRM,
> orders in an OMS, product master data and engineering changes
> in a PDM, stock and suppliers in an SCM system — all Postgres.
> And the OT world: every end-of-line test, every material issue
> streams over the Solace event mesh into a plant data store.
>
> The interesting part: engineering just released a change,
> ECO-2025-118 — a new sintered clutch disc, used in BOTH
> divisions, with a new torque test spec. Hamburg acknowledged
> it. Graz — you'll see. And one more number to remember: when
> Acme's parts stop an OEM customer's line, the penalty is
> 45,000 euros per hour. Today, AI workers keep both promises:
> quality, and the line never stops."

## 3. HIRING — the roster and the gap (2:30–3:30)

**DO**: window A -> Agent Management. Verified during pre-flight:
the Shop Floor Analyst is ABSENT while the
`mfg-telemetry`/`mfg-consumption` connectors are PRESENT
(pre-provisioned workplace infrastructure).

**SAY**: the team — Orchestrator (team lead), four query experts
(CRM, OMS, PDM, SCM — one per system, each bound to its own
connector), a confirmation clerk for routine work, and two
specialists that only merge: the Quality Incident Reporter and
the Supply Chain Watcher, whose standing brief is "production
never stops". **The gap**: nobody can see the shop floor — all
that station telemetry and material consumption streaming into
MongoDB has no analyst. Let's hire one.

## 4. ONBOARDING — Build with AI (3:30–4:30)

**DO**: window A -> Sidebar -> **Builder** -> **Build with AI**
(Quick Build). Paste the prompt below and send it. Watch for
~10 s that it actually starts building (if it asks a clarifying
question instead, answer in one line — it is
non-deterministic). Then leave it running and move on to
section 5. Reference result =
`fallback/agents/Shop Floor Analyst.yaml`.

The two MongoDB connectors (`mfg-telemetry`,
`mfg-consumption`) are PRE-PROVISIONED by install.sh — the
Builder only creates the AGENT that binds them. One config, no
connector sub-tasks, no cross-component validation: this is the
optimization after the bumpy 2026-08-11 run (see Appendix C).

Click rule: as soon as the agent config has validated and the
plan card is up, click **Build & Activate** yourself — do not
wait for the Builder to keep validating. In the Review step,
check TWO fields before deploying:

1. NAME must read exactly "Shop Floor Analyst" (observed
   2026-08-11: the Builder can normalize it to
   "ShopFloorAnalyst" — the workflows reference the exact
   name).
2. TOOLS in the plan card: the agent config must contain the
   two builtin tool groups (data_analysis +
   artifact_management). NOTE: after deploy, the Toolsets
   field in Agent Management may show EMPTY even when the
   tools are fine — that field only mirrors UI-assigned
   toolsets; the truth is the runtime (verified via awe logs:
   chart + artifact tools registered). Do not "fix" an empty
   Toolsets field on stage.

Name fixes stay in the UI (Review card, or Agent Management ->
edit -> save & redeploy, ~15 s) — no fallback needed.

**Break glass** (Builder fails or stalls — see Appendix C):
run this in the terminal — it creates the identical agent
declaratively in ~20 s (requires the pre-flight
`sam auth login`), then continue at 6.1. NEVER `--prune`. The
apply is idempotent: it also just ADDS whatever is missing
(agent and/or connectors).

```bash
cd ~/Documents/GitHub/solace-demo-artifacts/sam-manufacturing-ops-demo/fallback && sam config apply
```

```text
Create an agent called "Shop Floor Analyst".

ROLE
Shop-floor (OT) data analyst for Acme Manufacturing. It answers
questions about end-of-line station telemetry and material
consumption from the plant data store (MongoDB) and compares
the OT reality with the plans in the IT systems.

SYSTEM ACCESS (bind existing platform connectors, create NOTHING)
Bind the two EXISTING MongoDB connectors "mfg-telemetry"
(collection station_telemetry) and "mfg-consumption"
(collection material_consumption). Both already exist on the
platform - reference them by exactly these names. Do NOT
create, copy or modify any connector. If any step or tool
claims MongoDB is not a supported connector type, that claim is
wrong and irrelevant here (no connector is being created):
ignore it and continue.

TOOLSETS (mandatory part of the agent config)
Enable exactly TWO tool groups on the agent: data_analysis and
the artifact tools (builder tool-group name:
artifact_management; platform toolset id:
builtin_artifact_tools). Declare them in the agent config as
builtin-group tool entries using the `tool_name` field (NOT
`group_name` - the schema rejects that). An agent config
without BOTH of these tool groups is WRONG even if it
validates - add them before validating. Do not add any other
toolsets. Model: the "reasoning" model alias - assigned at the
platform level; do NOT put a `model` field inside app_config
(the schema rejects it there too).

DATA SHAPES (for the agent's instruction)
station_telemetry (one doc per EOL test): plant{plant_id,
plant_name, city, country}, line_id, station_id, prod_order_id,
product{material_id, name}, serial_no, test{type, measured,
unit, spec_min, spec_max, station_spec_revision},
result (PASS|FAIL), failure_code, cycle_time_s, operator_id,
shift.
material_consumption (one doc per material issue):
plant{plant_id, plant_name}, material_id, description,
prod_order_id, line_id, qty_issued, balance_after, uom.

BEHAVIOR RULES (put these into the agent's instruction)
- Query with MongoDB aggregation pipelines only; timestamps are
  BSON dates, use $dateToString for daily grouping.
- Fail-rate answers report measured vs spec_min/spec_max AND
  the station_spec_revision - a station testing a new design
  against an old spec revision is a master-data signal, call it
  out.
- Consumption answers report the daily rate, when a ramp
  started and the latest balance_after - clearly labeled as the
  OBSERVED rate (the planned rate lives in the SCM system).
- Save large result sets as artifacts, summarize the key
  findings, and render a chart when a visualization helps.

BUILD INSTRUCTIONS (follow exactly, no deviations)
1. Everything you need is in this prompt. Do NOT ask clarifying
   questions and do NOT pause for confirmation between phases.
   Run discovery, design and config generation sequentially in
   THIS session - do NOT spawn parallel sub-tasks.
2. This build creates exactly ONE component: the agent.
3. Use the exact name "Shop Floor Analyst" for the agent config
   AND the manifest entry (no slug variants, no CamelCase).
4. Connector wiring - this exact structure, decide ONCE:
   a. In the BUILD MANIFEST, include "mfg-telemetry" and
      "mfg-consumption" as components with origin: platform and
      status: deployed (pre-existing - generate NO connector
      configs and create nothing).
   b. In the AGENT CONFIG, declare the connectors at the APP
      level, as a SIBLING of app_config - NOT inside
      app_config (the app_config schema rejects the field
      there):
        connectors:
          - mfg-telemetry
          - mfg-consumption
   This combination is the verified wiring: manifest components
   with platform origin + app-level connectors list.
5. Validation order: first validate the agent config
   INDIVIDUALLY (after the toolsets are in). Then run the full
   build-manifest validation ONCE - with the structure from
   step 4 it PASSES. If it fails anyway, do not loop and do
   not restructure: re-check that connectors sit at the app
   level (not in app_config) and that both manifest components
   carry origin: platform, fix ONLY that, and validate once
   more.
6. After the green full validation: no further config edits.
   Declare the build ready for Build & Activate and STOP.

DEFINITION OF DONE (verify every point, then stop)
- Agent name is exactly "Shop Floor Analyst".
- The manifest lists mfg-telemetry and mfg-consumption on the
  agent as existing platform connectors; there are NO new
  connector components.
- The agent config enables data_analysis AND the artifact tool
  group.
- The agent config declares the connectors at the app level
  (sibling of app_config, never inside it).
- The agent config passed the individual validation AND the
  full build-manifest validation is green.
```

**SAY** (while pasting and sending):

> "This prompt is a job posting: role, responsibilities,
> expectations — including domain rules like 'a station testing
> a new design against an old spec revision is a master-data
> signal'. And the onboarding package: system access. Note HOW
> access works here — IT has already provisioned **two governed,
> read-only connections** into the plant store; the new hire
> gets **bound** to them, it never sees credentials. And what I
> did **not** paste: no API key, no model endpoint. The agent
> gets a model **alias** — the `reasoning` tier: an analyst
> doing data work gets the cost-efficient model, not the
> premium tier.
>
> Hiring takes a minute — so while HR does the paperwork, let
> me show you around the new colleague's workplace."

## 5. The workplace tour — while the Builder runs (4:30–7:30)

Five stops, two or three sentences each; glance at the Builder
tab between stops and do not comment on it until section 6. The
tour is elastic filler: extend the models stop if the Builder
is slow, cut toolsets/skills if it finished early.

1. **Workflows** — open `quality-incident-report` (direct link
   via `./demo-links.sh`): the standard operating procedure.
   Three specialists investigate in parallel, a fourth merges;
   `fail_fast` off — a missing specialist is reported
   transparently instead of failing. All YAML in git, applied
   with `sam config apply`. The floor node references the
   analyst being hired RIGHT NOW.
2. **Connectors** — the governed data access of the team.
3. **Entrypoints** — `plant-events` with its three event rules.
4. **Models** — the aliases: `fast` for routine confirmations,
   `general` for the experts, `workflow` for the merges,
   `reasoning` for the analyst — multi-model by task, no API
   key ever visible.
5. **Toolsets and skills** — versioned schema knowledge
   (`mfg-*-schema`), first cut on overrun.

Show the TWO deployed workflows (`quality-incident-report`,
`supply-replenishment`) and the `plant-events` entrypoint with
its three event rules.
On the Connectors stop, point at `mfg-telemetry` and
`mfg-consumption`: the plant-store access the new hire is being
bound to RIGHT NOW — read-only service account, one collection
each, provisioned by IT before the hire. Event rules:
released orders -> clerk (fast tier), eol-failed -> incident,
threshold-crossed -> replenishment. The two-altitude story
belongs HERE:

> "Two kinds of events on the mesh. The telemetry firehose —
> every test, every material issue, thousands of guaranteed-
> delivery events — lands in the plant store; no language model
> ever sees it. And the business-significant events — a failure
> signature, a threshold crossing — THOSE trigger agents.
> Agents are event subscribers like any other microservice:
> they don't poll, and they don't get spammed."

## 6. ONBOARDING complete — deploy and first task (7:30–9:30)

Deploy the Shop Floor Analyst, then first task in window B
(talk to the data), e.g.:

> "What is the daily EOL fail rate for the IX-450 on Plant 2
> line L3, and when did the failures start?"

Expected: fail rate jumps around 2025-07-28, measured ~22 Nm vs
spec 17.5–18.5, station spec revision B. Leave the answer open —
it foreshadows movement 1.

## 7. TEAMWORK — the cockpit, two movements (9:30–16:30)

**DO**: open `cockpit/index.html` (green LED = connected to the
sam VPN via ws://localhost:8008). ONE click: **Release orders**.

Timeline after the click (scripted in the cockpit,
deterministic):

Timings below are MEASURED (dress rehearsal 2026-08-11, all
13 tasks completed, zero failures):

- **0:00** -- two order-released events; the clerk confirms both
  in ~6 s each (fast tier). The good case, 30 seconds.
- **0:25** -- Graz L3 starts failing (HD-22 units vs the old
  spec). Let the counters climb.
- **~0:45** -- 6th fail publishes ONE `eol-failed` event; the
  incident analysis starts. Movement 1: narrate via Activities
  in window B — open the running task and let the delegation
  tree speak. The Orchestrator delegates
  OMS first, then PDM + Shop Floor Analyst -- the analyst runs
  ~9 aggregation pipelines and renders a CHART live (say so:
  the colleague hired 15 minutes ago is making charts).
- **~4:40** -- the coverage gauge crosses the red line;
  `threshold-crossed` fires, the replenishment analysis starts
  -- this time the Orchestrator fans out to SCM + OMS + analyst
  IN PARALLEL (visible in Activities). Movement 2: "nobody
  asked a question".
- **~5:15** -- the incident report lands in the cockpit. (Both
  movements overlap for a minute -- that is fine and even makes
  the point: the team walks and chews gum.)

  **READ ALOUD** (wording varies per run; the rehearsal run
  produced these lines -- pick the bottom line + one kicker):

  > "This is a **false-reject** caused by an ECO distribution
  > gap, **not a defective product**." ... 69.6 % fail rate,
  > 100 % from July 28 -- "sustained failures begin **three
  > minutes** after the first HD-22 lot issue" -- station still
  > on spec revision B. 1,800 units, 340,000 euros at risk.

  **SAY**: "No engineer wrote that. Five systems, one story:
  recalibrate the station, re-test the held units -- they are
  very likely GOOD -- and have Graz acknowledge the change.
  The parts were never the problem. The data was."
- **~8:15** -- the replenishment recommendation lands.

  **READ ALOUD** (rehearsal wording):

  > "The safety-stock buffer was sized for a **120/day plan**,
  > but the ECO ramp is burning **3.5 to 4 times** that --
  > **~4 days of cover**, and if the PO slips a single day,
  > the line stops." The ONE action: "**expedite 3,000 units
  > from the qualified alternate TODAY, 3-day delivery** --
  > and reset the MRP parameters to the observed rate."

  **SAY**: "784,000 euros of unshipped OEM orders behind that
  material -- and remember Volta's 45,000-per-hour line-down
  penalty. Nobody ran a report. The threshold event did."

  ELASTIC BRIDGE: after reading the incident report (~5:30),
  start chapter 8 on the dashboard and RETURN to the cockpit
  when the recommendation arrives -- do not wait idle.

**SAY** (the pivot between the movements):

> "You just watched the team investigate a failure after it
> happened. Now watch them prevent the next one before it
> happens — same events, same mesh, no one asked a question.
> Hamburg adopted that same engineering change and is burning
> the new clutch disc four times faster than the plan knows.
> Watch the gauge."

**Break-glass**: footer buttons in the cockpit re-fire either
business event without restarting the flow.

## 8. IMPROVEMENT — measure the workforce (16:30–18:45)

**DO**: window D — Grafana dashboard "SAM Manufacturing Ops
Demo". Walk the rows top to bottom; every number was produced
by the run the audience just watched:

1. **Health** — components up, broker connections, tasks in
   flight: the workforce has an ops view like any other system.
2. **Speed** — request duration p50/p95 and LLM latency per
   model: the clerk's fast tier visibly answers in seconds
   while the experts think.
3. **Cost + chargeback** — token rate by model, and the
   platform-DB table BY USER: the event-driven runs all landed
   on `power_user` — chargeback works for AI workers.
4. **Governance** — the audit stream from Loki: every tool
   execution with its user; RBAC denies included.
5. **The proof** — one Tempo trace of the incident run (every
   A2A hop is a broker span), and the offline evals in the
   Evaluations lab: the `mfg-ops-quality` gate plus the
   three-model `mfg-ops-model-benchmark` on the PDM expert —
   pre-run before the event.

Cost beat, with the rehearsal's REAL numbers (task metadata):

> "What did that just cost? The entire incident
> investigation — five agents across five systems — was
> **187,000 tokens**; the replenishment run **147,000**. At
> list prices that is a couple of euros — versus a quality
> engineer spending an afternoon reconciling OMS, PDM and
> shop-floor exports, while the held order ages. And every
> token is attributed: the chargeback table shows it all under
> the operations persona that owns the event rules."

## 9. WRAP (18:45–20:00)

Close the lifecycle: hired live, onboarded with governed system
access, teamwork triggered by events end to end — reactive AND
proactive — measured to the token. **DO**: re-show slide 2 —
the movement cards are now what the audience just watched
happen, and the bottom strip is the closer: one click -> one
event -> react + prevent -> no human in the loop.

> "One engineering change, badly propagated, and the same
> platform caught both consequences: the quality incident it
> caused, and the stockout it was about to cause. That is what
> event-driven AI operations look like: the enterprise nervous
> system doing the noticing, and AI workers doing the thinking
> — governed, audited, and measured like any other workforce."

## Appendix A — Pre-flight checklist (15 min before going live)

**Automated: run `./preflight.sh`** — it checks every item
below, applies the fix on failure (install.sh, seed, mongo
reseed, analyst removal, dashboard apply, eval pre-run) and
ends with READY / NOT READY. The list below is the manual
reference; only the window setup and the break-glass rehearsal
remain human steps.

1. Base platform healthy: models probe
   (`agent-mesh-deployment/scripts/models/apply-models.sh
   --probe-only`), all pods Running (kyverno, monitoring,
   sam-solace-lab).
2. `./install.sh` ran clean; **Agent Management shows NO Shop
   Floor Analyst**, but the `mfg-telemetry` and
   `mfg-consumption` connectors ARE present (pre-provisioned;
   the live Builder beat only creates the agent binding them).
3. Postgres: `postgres/seed.sh` re-run is idempotent; spot-check
   `SELECT status FROM mfg_eco_distribution WHERE plant_id =
   'PLANT_GRZ' AND eco_id = 'ECO-2025-118';` -> PENDING.
4. MongoDB: `docker exec mfg-plant-mongo mongosh ...` count
   documents (~960 telemetry, ~290 consumption).
5. Cockpit LED green; break-glass buttons tested in rehearsal;
   then RESET.
6. Evals pre-run (~15 min): `sam eval run mfg-ops-quality`,
   `sam eval run mfg-ops-model-benchmark`.
7. Windows: A = sam_admin (Agent Management), B = power_user
   (Activities), C = cockpit, D = Grafana dashboard.

## Appendix B — Extra queries and product stories

- Results recap: `results/acme-workflow-results.html` renders
  both reports as one polished page (KPIs, findings, the one
  concrete action) -- open it after the movements as the
  "here is what just happened" recap, or send it as the
  leave-behind.
- CRM: "Which OEM accounts have the highest line-down penalty?"
  (Volta 45k EUR/h — the number behind movement 2.)
- SCM: "Days of cover for MAT_CLT_HD22 at PLANT_HAM at planned
  vs an observed rate of 460/day?" (15.4 vs ~4 days.)
- PDM: "Which ECOs are pending acknowledgement?" (the root
  cause, queryable at any time.)
- OMS: "Which production orders are on quality hold?"
  (PRD-118-4718 — pre-seeded so the data story holds even
  before the live event fires.)

## Appendix C — Known limits (moderate honestly)

Platform-level limitations (verified on this build): entrypoint
promptTemplate renders only for AGENT targets, hence the
Orchestrator route while the workflows carry the UI story;
event-triggered runs deliver no structured input keys
({{workflow.input}} raw); merge agents must have no toolsets.
Manufacturing-specific: the cockpit timeline is scripted —
deterministic on purpose; say so if asked ("the data stores are
real, the event timing is compressed for stage").

Builder failure signatures (all observed 2026-08-11, and the
reason the connectors are now pre-provisioned so the live build
creates ONLY the agent):

- Name normalization: "ShopFloorAnalyst" without spaces,
  connector "mfg-plant-mongodb". The workflows and the
  Orchestrator prompts reference the EXACT name
  "Shop Floor Analyst" -- in the Review step before deploying,
  check the name field and correct it, otherwise the floor
  sections of both movements report the peer as missing.
- Connector sub-task hallucination: when the Builder fans
  connector creation out to parallel sub-tasks, one can claim
  "MongoDB is not supported (only DynamoDB, Neo4j, Neptune)".
  It IS supported (`document_db`/`mongodb`, experimental in
  this build) -- the fallback configs prove it. With the
  agent-only build this path no longer exists.
- "Couldn't confirm full validation -- deploy stays disabled
  until it succeeds": the deploy gate reflects the LAST
  validation result. RESOLVED 2026-08-11: the full validation
  is NOT unsatisfiable -- it passes
  when (a) the two connectors are manifest components with
  origin: platform / status: deployed AND (b) the agent config
  declares `connectors` at the APP level, as a sibling of
  app_config. Inside app_config the schema rejects the field
  -- that one-level difference caused every earlier failure
  and flip-flop. The prompt now mandates the exact structure;
  full validation is expected GREEN. If the banner still
  appears: one "rerun validation" in the Builder chat, and if
  the gate stays red, break glass
  (`cd fallback && sam config apply`) and continue at 6.1.
- A long pasted prompt may be attached as a `snippet.txt` file
  instead of inline text -- harmless, the Builder loads it;
  the shortened agent-only prompt usually stays inline.
- Connectors-field flip-flop (observed 2026-08-11, agent-only
  build): the cross-component validator demands a connectors
  declaration, the app_config schema rejects the field INSIDE
  app_config, and the Builder oscillates between adding and
  removing it, burning minutes. Root cause resolved: the field
  belongs at the APP level (sibling of app_config) -- see the
  deploy-gate entry below; the prompt now states the exact
  placement, so neither the flip-flop nor the failing full
  validation should occur.
- Toolset loss (observed 2026-08-11, RESOLVED same day): one
  run deployed with no runtime tools beyond the connector
  queries (no artifacts, no charts). Root cause: the tool
  groups never made it into the agent config. With the prompt's
  TOOLSETS block (builtin-group entries via `tool_name`, not
  `group_name`) the tools reach the runtime -- verified in the
  awe logs (create_chart_from_plotly_config registered).
  CAVEAT: the platform's Toolsets field in Agent Management
  shows EMPTY either way -- it only mirrors UI-assigned
  toolsets, not app_config tools. Judge by the plan card / awe
  logs, never by that field.

Artifact pass-through: charts rendered by a delegated agent
(e.g. the analyst's torque-trend PNG) live in THAT agent's
session; the merge report references them but may not embed
them, and the final answer says so transparently. Not a bug to
apologize for on stage -- if asked, open the analyst's task in
Activities and show the chart there ("every artifact is
session-scoped and auditable").

Date reconciliation: the plant dataset lives in Jul/Aug 2025
(matching the ECO-2025-118 numbering) while live events carry
today's timestamp. The agents NOTICE and reconcile this
transparently ("treated as the ramp window") -- observed in
the rehearsal's replenishment caveats. If asked: "the dataset
is historic, the event stream is live -- and the analyst
reconciled the two on its own, which is exactly what you want
an analyst to do."

Merge agents may WARN with a pseudo-tool `_continue_generation`
(observed 2026-08-11 at the Quality Incident Reporter, three
WARN lines): the model tries to continue a long answer via a
tool that does not exist. NOT fatal -- the task completed and
the report was delivered. Only if a report visibly ends
mid-sentence, tighten the "under 25 lines" rule in the merge
agent's prompt.

The Builder depends on the external LLM gateway
(lite-llm.mymaas.net): a transient upstream 502 surfaces as
"The AI provider returned an unexpected HTML response (HTTP
502)" (observed 2026-08-10, single occurrence, retry
succeeded). On stage: retry ONCE, and if it fails again switch
to the break-glass without commentary —
`cd fallback && sam config apply` (NEVER `--prune`) creates
the Shop Floor Analyst + connectors in seconds and the demo
continues at "Review and deploy".
