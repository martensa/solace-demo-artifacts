# Event-Driven Manufacturing Operations — Live Demo Script

> **Status: v0.1 skeleton.** Structure, beats, click paths and
> the two event-driven movements are final; the verbatim SAY
> blocks are drafted but not yet rehearsal-hardened the way
> `sam-retail-ops-demo/talk-track.md` is. Rehearse, then refine
> in place. Where a beat is identical to retail (tour, RBAC,
> observability mechanics), this file references the retail
> script instead of duplicating it.

**Title slide:** Event-Driven Manufacturing Operations —
*The Line Never Stops.*

The red thread is the AI Worker Lifecycle (HIRE -> ONBOARD ->
TEAMWORK -> IMPROVE), identical to the retail demo. What is new:
TEAMWORK has **two movements** from **one click** —

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

Same personas as retail (see retail talk-track section
"Personas and RBAC"): window A `sam_admin` (hiring manager,
Agent Management + Builder), window B `power_user@solace.lab`
(operations persona; all event-triggered runs are attributed to
it via `defaultUserIdentity` and show up in ITS Activities and
the chargeback panel).

## Timing at a glance (20:00 total)

| # | Beat | Time |
| --- | --- | --- |
| 1 | Lifecycle — slide 1 | 0:00–1:00 |
| 2 | Scenario — slide 2 (Acme Manufacturing) | 1:00–2:30 |
| 3 | HIRING — roster and the gap | 2:30–3:30 |
| 4 | ONBOARDING kickoff — Build with AI | 3:30–4:30 |
| 5 | Workplace tour (while the Builder runs) | 4:30–7:30 |
| 6 | ONBOARDING complete — deploy + first task | 7:30–9:30 |
| 7 | TEAMWORK — the cockpit, two movements | 9:30–16:30 |
| 8 | IMPROVEMENT — measure the workforce | 16:30–18:45 |
| 9 | WRAP — the lifecycle, closed | 18:45–20:00 |

## 2. Scenario — slide 2 (1:00–2:30)

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
Shop Floor Analyst and the `mfg-telemetry`/`mfg-consumption`
connectors are ABSENT.

**SAY**: the team — Orchestrator (team lead), four query experts
(CRM, OMS, PDM, SCM — one per system, each bound to its own
connector), a confirmation clerk for routine work, and two
specialists that only merge: the Quality Incident Reporter and
the Supply Chain Watcher, whose standing brief is "production
never stops". **The gap**: nobody can see the shop floor — all
that station telemetry and material consumption streaming into
MongoDB has no analyst. Let's hire one.

## 4. ONBOARDING — Build with AI (3:30–4:30)

**DO**: window A -> Build with AI. Builder prompt (reference
result = `fallback/agents/Shop Floor Analyst.yaml`):

> Create an agent "Shop Floor Analyst" — a shop-floor data
> analyst for Acme Manufacturing. Data source: MongoDB at
> host.docker.internal, port 27017, database mfg_plant,
> username sam_ro, password sam_ro, authSource mfg_plant. Two
> collections: station_telemetry (one document per end-of-line
> test: plant, line_id, station_id, prod_order_id, product,
> test with measured/spec_min/spec_max/station_spec_revision,
> result PASS or FAIL, failure_code) and material_consumption
> (one document per material issue: plant, material_id,
> prod_order_id, qty_issued, balance_after). It answers
> questions with aggregation pipelines: fail rates by line and
> product, measured values vs spec over time, observed daily
> consumption rates and ramps. Use the reasoning model.

**Fallback (break-glass)**: `cd fallback && sam config apply`
— NEVER `--prune`. If the Builder created only one connector,
the fallback apply adds the missing one idempotently.

## 5. The workplace tour — while the Builder runs (4:30–7:30)

Same structure as retail section 5 (workflows, connectors,
entrypoints, models, toolsets/skills) — show the TWO deployed
workflows (`quality-incident-report`, `supply-replenishment`)
and the `plant-events` entrypoint with its three event rules:
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

- **0:00** -- two order-released events; the clerk confirms both
  (fast tier). The good case, 30 seconds.
- **0:25** -- Graz L3 starts failing (HD-22 units vs the old
  spec). Let the counters climb.
- **~0:40** -- 6th fail publishes ONE `eol-failed` event; the
  incident analysis starts. Movement 1: narrate via Activities
  in window B, like retail 7.3/7.4.
- **~4:00** -- the incident report lands in the cockpit. Read
  severity + root cause: ECO pending at Graz.
- **~4:40** -- the coverage gauge crosses the red line;
  `threshold-crossed` fires, the replenishment analysis starts.
  Movement 2: "nobody asked a question".
- **~7:00** -- the replenishment recommendation lands. Read the
  one action: expedite / alternate supplier before stockout.

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

Same mechanics as retail section 8, with the manufacturing
dashboard ("SAM Manufacturing Ops Demo" in Grafana): health,
speed (fast vs general tier visible from the clerk vs experts),
cost + chargeback by user (power_user carries the event-driven
runs), audit stream, one Tempo trace of the incident run, and
the offline evals (`mfg-ops-quality` gate + the three-model
`mfg-ops-model-benchmark` on the PDM expert) — pre-run before
the event.

## 9. WRAP (18:45–20:00)

Close the lifecycle: hired live, onboarded with governed system
access, teamwork triggered by events end to end — reactive AND
proactive — measured to the token. One slide with the causal
chain diagram: one click -> one event -> two business outcomes.

> "One engineering change, badly propagated, and the same
> platform caught both consequences: the quality incident it
> caused, and the stockout it was about to cause. That is what
> event-driven AI operations look like: the enterprise nervous
> system doing the noticing, and AI workers doing the thinking
> — governed, audited, and measured like any other workforce."

## Appendix A — Pre-flight checklist (15 min before going live)

1. Base platform healthy (see retail Appendix A items: models
   probe, kyverno/monitoring health).
2. `./install.sh` ran clean; **Agent Management shows NO Shop
   Floor Analyst and NO mfg-telemetry/mfg-consumption
   connectors** (the live Builder beat depends on it).
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

Inherited from the platform (see retail Appendix C): entrypoint
promptTemplate renders only for AGENT targets, hence the
Orchestrator route while the workflows carry the UI story;
event-triggered runs deliver no structured input keys
({{workflow.input}} raw); merge agents must have no toolsets.
Manufacturing-specific: the cockpit timeline is scripted —
deterministic on purpose; say so if asked ("the data stores are
real, the event timing is compressed for stage").
